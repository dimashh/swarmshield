"""SwarmShield hub: rounds, red/blue boards, events and the derived /api/state (CONTRACTS §8-10)."""
import json
import math
import threading
import time
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from common.schema import RED_AGENTS, TRUST_IGNORE_BELOW, TRUST_START

STATIC = Path(__file__).parent / "static"
EVENTS_LOG = Path(__file__).resolve().parent.parent / "events.jsonl"
BOARD_KEEP, BLUE_KEEP, COMMENTARY_KEEP, STEPS_KEEP, BLOCKS_KEEP, REQUESTS_KEEP = 14, 10, 4, 40, 12, 40
SPLIT_AT_LONE = 3

app = FastAPI(title="SwarmShield hub")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

lock = threading.Lock()


class Round:
    def __init__(self, rid=0, shield=False, running=False):
        self.id, self.shield, self.running = rid, shield, running
        self.started_at = time.time()
        self.stopped_at = None
        self.board, self.blue, self.commentary = [], [], []
        self.agents = {a: {"id": a, "stage": 0, "stage_real": 0, "stage_fake": False, "status": "active",
                           "cost": 0.0, "steps": 0, "thought": "", "reality": None,
                           "flagged": False, "lone": False, "won": False} for a in RED_AGENTS}
        self.trust = {(a, b): TRUST_START for a in RED_AGENTS for b in RED_AGENTS if a != b}
        self.links = []
        self.contradictions = 0
        self.flagged = set()
        self.time_to_detect = None
        self.time_to_split = None
        self.time_to_flag = None
        self.captured_by = None
        self.defender_cost = 0.0
        self.real_hits_after_detect = 0
        self.legit_ok = self.legit_fail = 0
        self.lone_order = []
        self.steps, self.blocks, self.detections, self.requests = [], [], [], []
        self.shopper = None

    def t(self):
        end = self.stopped_at or time.time()
        return round(end - self.started_at, 1) if self.id else 0.0


R = Round()
last_id = 0
results: list = []


def _log(ev):
    try:
        with EVENTS_LOG.open("a") as f:
            f.write(json.dumps(ev) + "\n")
    except OSError:
        pass


def _comment(kind, text):
    R.commentary.append({"t": R.t(), "kind": kind, "text": text})


def _agent(aid):
    return R.agents[aid]


def _num(v):
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _avg_trust():
    return round(sum(R.trust.values()) / len(R.trust), 2) if R.trust else 0.0


def _apply(ev):
    typ = ev.get("type")
    if typ == "step" and ev.get("agent") in R.agents:
        ag = _agent(ev["agent"])
        ag["steps"] += 1
        R.steps.append({"id": len(R.steps) + 1, "t": ev["t"], "agent": ag["id"], "method": ev.get("method", "GET"),
                        "path": ev.get("path"), "status": ev.get("status"), "stage": ev.get("stage"),
                        "lead_from": ev.get("lead_from"), "thought": ev.get("thought"),
                        "in_reality": ag["flagged"]})
        ag["cost"] = round(ag["cost"] + _num(ev.get("cost")), 6)
        if ev.get("thought"):
            ag["thought"] = ev["thought"]
        stage = int(ev.get("stage") or 0)
        ag["stage"] = max(ag["stage"], stage)
        if not ag["flagged"]:
            ag["stage_real"] = ag["stage"]
    elif typ == "trust":
        key = (ev.get("a"), ev.get("b"))
        if key in R.trust:
            R.trust[key] = max(0.0, min(1.0, _num(ev.get("value"))))
    elif typ == "contradiction":
        R.contradictions += 1
    elif typ == "lone" and ev.get("agent") in R.agents:
        ag = _agent(ev["agent"])
        if not ag["lone"]:
            ag["lone"] = True
            R.lone_order.append(ag["id"])
            n = len(R.lone_order)
            _comment("lone", f"{ag['id']} no longer trusts anyone. {n} agent{'s' if n > 1 else ''} lone.")
            if n == SPLIT_AT_LONE and R.time_to_split is None:
                R.time_to_split = R.t()
                _comment("split", f"Swarm split after {R.time_to_split}s. Shared knowledge is now poison.")
    elif typ == "flag_captured":
        aid = ev.get("agent")
        if aid in R.agents:
            _agent(aid)["won"] = True
            _agent(aid)["stage"] = _agent(aid)["stage_real"] = 5
        if R.captured_by is None:
            R.captured_by = aid
            R.time_to_flag = R.t()
            _comment("loss", f"{aid} captured the flag after {R.time_to_flag}s.")
    elif typ == "legit":
        R.shopper = {"t": ev["t"], "method": ev.get("method"), "path": ev.get("path"), "status": ev.get("status")}
        if int(ev.get("status") or 0) < 400:
            R.legit_ok += 1
        else:
            R.legit_fail += 1
    elif typ == "request":
        s = ev.get("session")
        if ev.get("routed") == "real" and s in R.flagged:
            R.real_hits_after_detect += 1
        if s in R.agents:
            R.requests.append({"t": ev["t"], "session": s, "method": ev.get("method", "GET"), "path": ev.get("path"),
                               "routed": ev.get("routed"), "status": ev.get("status")})
            del R.requests[:-REQUESTS_KEEP]
        elif ev.get("routed") == "forward_legit":
            R.shopper = {"t": ev["t"], "method": ev.get("method"), "path": ev.get("path"), "status": ev.get("status")}
    elif typ == "canary_link":
        link = {"a": ev.get("a"), "b": ev.get("b"), "token": ev.get("token")}
        if not any(l["a"] == link["a"] and l["b"] == link["b"] for l in R.links):
            R.links.append(link)
    elif typ == "warden_block":
        R.blocks.append({"t": ev["t"], "session": ev.get("session"), "item": ev.get("item"),
                         "from": ev.get("from"), "status": ev.get("status")})
    elif typ == "detected":
        R.detections.append({"t": ev["t"], "sessions": ev.get("sessions") or [], "reason": ev.get("reason")})
        if R.time_to_detect is None:
            R.time_to_detect = R.t()
        for s in ev.get("sessions") or []:
            R.flagged.add(s)
            if s in R.agents:
                _agent(s)["flagged"] = True
    elif typ == "reality_assigned" and ev.get("session") in R.agents:
        f = ev.get("facts") or {}
        ag = _agent(ev["session"])
        ag["flagged"] = True
        R.flagged.add(ev["session"])
        ag["reality"] = {"admin_path": f.get("admin_path"), "api_key": f.get("api_key"),
                         "flag_hint": f.get("flag_hint"), "warden": ev.get("warden")}
    elif typ == "defender_cost":
        R.defender_cost = _num(ev.get("usd"))
    elif typ == "commentary":
        _comment(ev.get("kind", "info"), ev.get("text", ""))


def _metrics():
    return {"contradictions": R.contradictions, "avg_trust": _avg_trust(), "lone_agents": len(R.lone_order),
            "time_to_detect": R.time_to_detect, "time_to_split": R.time_to_split,
            "time_to_flag": R.time_to_flag,
            "attacker_cost": round(sum(a["cost"] for a in R.agents.values()), 4),
            "defender_cost": round(R.defender_cost, 6), "real_hits_after_detect": R.real_hits_after_detect,
            "attacker_success": 1 if R.captured_by else 0, "legit_ok": R.legit_ok, "legit_fail": R.legit_fail}


def _legit_pct():
    total = R.legit_ok + R.legit_fail
    return round(100 * R.legit_ok / total) if total else 100


def _status(ag):
    if ag["won"]:
        return "won"
    if ag["lone"]:
        return "lone"
    if ag["flagged"]:
        return "flagged"
    return "active"


def _stop():
    if not R.running:
        return
    R.running = False
    R.stopped_at = time.time()
    m = _metrics()
    if R.shield and not R.captured_by:
        _comment("win", f"Round over. Flag safe, trust {m['avg_trust']}, legit {_legit_pct()}%.")
    results.append({"round": R.id, "shield": R.shield, "flag": bool(R.captured_by),
                    "time_to_flag": R.time_to_flag, "time_to_split": R.time_to_split,
                    "time_to_detect": R.time_to_detect, "avg_trust": m["avg_trust"],
                    "contradictions": R.contradictions, "lone_agents": m["lone_agents"],
                    "legit_pct": _legit_pct(), "attacker_cost": m["attacker_cost"],
                    "defender_cost": m["defender_cost"]})


# ---- rounds ----------------------------------------------------------------
def _stale(rid):
    return rid is not None and rid != R.id


@app.post("/api/round/{mode}")
def round_ctl(mode: str, round: int | None = None):
    global R, last_id
    with lock:
        if mode == "stop":
            if not _stale(round):
                _stop()
            return {"ok": True}
        if mode not in ("on", "off"):
            return {"ok": False, "error": "mode must be on, off or stop"}
        _stop()
        last_id += 1
        R = Round(last_id, shield=(mode == "on"), running=True)
        _comment("info", f"Round {R.id} started. Shield {'ON' if R.shield else 'OFF'}.")
        return {"id": R.id, "shield": R.shield}


@app.get("/api/round")
def round_get():
    return {"id": R.id, "shield": R.shield, "running": R.running, "t": R.t()}


@app.post("/api/reset")
def reset():
    """Hotkey X: clear everything, including the scorecard."""
    global R
    with lock:
        R = Round()
        results.clear()
    return {"ok": True}


# ---- boards ----------------------------------------------------------------
@app.post("/api/board")
def board_post(post: dict = Body(...)):
    with lock:
        if _stale(post.get("round")):
            return {"ok": False, "error": "stale round"}
        p = {"author": post.get("author"), "kind": post.get("kind", "finding"), "text": post.get("text", ""),
             "leads": post.get("leads") or [], "secrets": post.get("secrets") or {},
             "contradicts": post.get("contradicts")}
        p.update(id=len(R.board) + 1, t=R.t())
        R.board.append(p)
        return p


@app.get("/api/board")
def board_get(since: int = 0):
    return [p for p in R.board if p["id"] > since]


@app.post("/api/blue")
def blue_post(post: dict = Body(...)):
    with lock:
        if _stale(post.get("round")):
            return {"ok": False, "error": "stale round"}
        p = dict(post)
        p.update(id=len(R.blue) + 1, t=R.t())
        R.blue.append(p)
        return p


@app.get("/api/blue")
def blue_get():
    return R.blue


# ---- events ----------------------------------------------------------------
@app.post("/api/events")
def events(body=Body(...)):
    evs = body if isinstance(body, list) else [body]
    with lock:
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            if _stale(ev.get("round")):
                continue
            ev["t"] = R.t()
            _log(ev)
            if R.running:
                _apply(ev)
    return {"ok": True}


# ---- state -----------------------------------------------------------------
@app.get("/api/state")
def state():
    with lock:
        agents = []
        for ag in R.agents.values():
            agents.append({"id": ag["id"], "stage": ag["stage"], "stage_real": ag["stage_real"],
                           "stage_fake": ag["flagged"], "status": _status(ag), "cost": round(ag["cost"], 4),
                           "steps": ag["steps"], "thought": ag["thought"], "reality": ag["reality"]})
        return {"round": R.id, "shield": R.shield, "running": R.running, "t": R.t(),
                "ended": R.id > 0 and not R.running, "captured_by": R.captured_by,
                "agents": agents,
                "trust": [{"a": a, "b": b, "value": round(v, 2)} for (a, b), v in R.trust.items()],
                "trust_ignore_below": TRUST_IGNORE_BELOW,
                "links": R.links,
                "board": R.board[-BOARD_KEEP:], "blue": R.blue[-BLUE_KEEP:],
                "commentary": R.commentary[-COMMENTARY_KEEP:],
                "steps": R.steps[-STEPS_KEEP:], "blocks": R.blocks[-BLOCKS_KEEP:],
                "detections": R.detections[-6:], "requests": R.requests, "shopper": R.shopper,
                "metrics": _metrics(), "legit_pct": _legit_pct(), "results": results}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
