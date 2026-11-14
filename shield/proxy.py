"""SwarmShield gateway: uvicorn shield.proxy:app --port 8080"""
import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from common import hub
from common.schema import H_AGENT, HUB_URL, LEGIT_TOKEN, POLL_ROUND_S, TARGET_URL, page
from shield.state import RoundState

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
HOP_BY_HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "te", "trailer",
              "upgrade", "proxy-authorization", "proxy-authenticate", "content-encoding", "accept-encoding"}


def is_legit(request: Request) -> bool:
    return request.headers.get("authorization", "") == f"Bearer {LEGIT_TOKEN}"


def _clean(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


async def poll_round(state: RoundState, client: httpx.AsyncClient):
    hub_down = False
    while True:
        try:
            r = (await client.get(f"{HUB_URL}/api/round")).json()
            if state.apply_round(r):
                print(f"[shield] round {state.id} shield={'ON' if state.shield else 'OFF'}: state cleared")
            hub_down = False
        except (httpx.HTTPError, ValueError) as e:
            if not hub_down:
                print(f"[shield] hub unreachable ({e!r}); keeping round {state.id}")
            hub_down = True
        await asyncio.sleep(POLL_ROUND_S)


def create_app(upstream_transport: httpx.AsyncBaseTransport = None, poll: bool = True, emit=None) -> FastAPI:
    state = RoundState()
    send = emit or (lambda type_, **f: hub.emit(type_, state.id, **f))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.upstream = httpx.AsyncClient(base_url=TARGET_URL, transport=upstream_transport, timeout=5.0)
        poller = None
        if poll:
            app.state.hub_client = httpx.AsyncClient(timeout=1.0)
            poller = asyncio.create_task(poll_round(state, app.state.hub_client))
        yield
        if poller:
            poller.cancel()
            await app.state.hub_client.aclose()
        await app.state.upstream.aclose()

    app = FastAPI(title="SwarmShield gateway", lifespan=lifespan)
    app.state.round = state

    async def forward(request: Request, path: str, body: bytes):
        try:
            r = await app.state.upstream.request(request.method, path, params=request.query_params,
                                                 headers=_clean(request.headers), content=body)
        except httpx.HTTPError as e:
            return JSONResponse(page("Bad gateway", "upstream unavailable", error="upstream unavailable"),
                                status_code=502), repr(e)
        return Response(r.content, status_code=r.status_code, headers=_clean(r.headers)), None

    @app.api_route("/{path:path}", methods=METHODS)
    async def gateway(request: Request, path: str):
        path = "/" + path
        session = request.headers.get(H_AGENT, "anonymous")
        body = await request.body()
        routed = "forward_legit" if is_legit(request) else "real"
        resp, err = await forward(request, path, body)
        if err:
            print(f"[shield] {request.method} {path} -> 502 ({err})")
        send("request", session=session, method=request.method, path=path, routed=routed,
             status=resp.status_code)
        return resp

    return app


app = create_app()
