"""Stand-in hub (CONTRACTS §8 subset) for running the shield before hub/app.py lands.
uvicorn shield.stubhub:app --port 8000. Adds GET /api/events for shield.rehearse."""
import time

from fastapi import FastAPI, Request

app = FastAPI(title="SwarmShield stand-in hub")
S = {"id": 0, "shield": False, "running": False, "started": time.time(), "board": [], "blue": [], "events": []}


def _t() -> float:
    return round(time.time() - S["started"], 3)


def _new_round(shield: bool) -> dict:
    S.update(id=S["id"] + 1, shield=shield, running=True, started=time.time(), board=[], blue=[], events=[])
    return {"id": S["id"], "shield": shield}


@app.post("/api/round/on")
def round_on():
    return _new_round(True)


@app.post("/api/round/off")
def round_off():
    return _new_round(False)


@app.post("/api/round/stop")
def round_stop():
    S["running"] = False
    return {"ok": True}


@app.get("/api/round")
def get_round():
    return {"id": S["id"], "shield": S["shield"], "running": S["running"], "t": _t()}


def _post(kind: str, body: dict) -> dict:
    post = {**body, "id": len(S[kind]) + 1, "t": _t()}
    S[kind].append(post)
    return post


@app.post("/api/board")
async def post_board(request: Request):
    return _post("board", await request.json())


@app.get("/api/board")
def get_board(since: int = 0):
    return [p for p in S["board"] if p["id"] > since]


@app.post("/api/blue")
async def post_blue(request: Request):
    return _post("blue", await request.json())


@app.get("/api/blue")
def get_blue():
    return S["blue"]


@app.post("/api/events")
async def post_events(request: Request):
    body = await request.json()
    for e in body if isinstance(body, list) else [body]:
        if e.get("round") == S["id"]:
            S["events"].append({**e, "t": _t()})
    return {"ok": True}


@app.get("/api/events")
def get_events():
    return S["events"]
