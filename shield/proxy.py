"""SwarmShield gateway: uvicorn shield.proxy:app --port 8080"""
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from common import hub
from common.schema import H_AGENT, HUB_URL, LEGIT_TOKEN, POLL_ROUND_S, TARGET_URL, page
from shield import canary, detect, wardens
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

    async def forward(method: str, path: str, query: str, headers: dict, body: bytes):
        try:
            r = await app.state.upstream.request(method, path + (f"?{query}" if query else ""),
                                                 headers=headers, content=body)
        except httpx.HTTPError as e:
            print(f"[shield] {method} {path} -> 502 ({e!r})")
            return None
        return r

    def bad_gateway():
        return JSONResponse(page("Bad gateway", "upstream unavailable", error="upstream unavailable"),
                            status_code=502)

    async def link_and_detect(session: str, hits: list):
        for tok, owner, _ in hits:
            if owner in (None, "real", session):
                continue
            if (owner, session, tok) not in state.links:
                state.links.add((owner, session, tok))
                send("canary_link", a=owner, b=session, token=tok)
            await flag(detect.on_link(state, owner, session), f"canary issued to {owner} replayed by {session}")

    async def flag(new: list, reason: str):
        if not new:
            return
        send("detected", sessions=sorted(state.flagged), reason=reason)
        send("commentary", kind="detect", text=f"{reason[0].upper()}{reason[1:]}. Swarm detected.")
        for s in new:
            await wardens.assign(state, s, send)

    @app.api_route("/{path:path}", methods=METHODS)
    async def gateway(request: Request, path: str):
        path = "/" + path
        session = request.headers.get(H_AGENT, "anonymous")
        query = request.url.query
        body = await request.body()
        headers = _clean(request.headers)

        if is_legit(request):
            state.legit.add(session)
            r = await forward(request.method, path, query, headers, body)
            resp = bad_gateway() if r is None else Response(r.content, r.status_code, _clean(r.headers))
            send("request", session=session, method=request.method, path=path, routed="forward_legit",
                 status=resp.status_code)
            return resp

        inbound = " ".join([path, query, *headers.values(), body.decode("utf-8", "replace")])
        await link_and_detect(session, canary.scan(inbound, state))

        if session in state.flagged:
            status, body_out = await wardens.handle(state, session, request.method, path, headers, body, send)
            send("request", session=session, method=request.method, path=path, routed="reality", status=status)
            return JSONResponse(body_out, status_code=status)

        sb = lambda t: canary.swap_back(t, state)  # noqa: E731
        r = await forward(request.method, sb(path), sb(query), {k: sb(v) for k, v in headers.items()},
                          sb(body.decode("utf-8", "replace")).encode() if body else body)
        if r is None:
            resp = bad_gateway()
        else:
            try:
                out = json.dumps(canary.outbound(r.json(), state, session)).encode()
            except ValueError:
                out = r.content
            resp = Response(out, r.status_code, _clean(r.headers))
            if r.status_code == 404:
                await flag(detect.on_404(state, session), f"{session} hit {state.n404[session]} dead routes")
        send("request", session=session, method=request.method, path=path, routed="real",
             status=resp.status_code)
        return resp

    return app


app = create_app()
