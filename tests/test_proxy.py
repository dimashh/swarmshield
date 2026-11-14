import json

import httpx
import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from common.schema import DETECT_404_LIMIT, LEGIT_TOKEN, REAL, canary, page
from shield.proxy import create_app

target = FastAPI()


@target.get("/api/docs")
def docs():
    return page("API docs", f"key {REAL['api_key']}", ["/api/v1/users"], {"api_key": REAL["api_key"]})


@target.get("/api/v1/users")
def users(x_api_key: str = Header(None)):
    if x_api_key != REAL["api_key"]:
        return page("Users", "no", error="invalid api key")
    return page("Users", "ok", [f"/backup/config-{REAL['cfg']}.bak"], {"cfg": REAL["cfg"]})


@target.get("/backup/config-{cfg}.bak")
def backup(cfg: str):
    if cfg != REAL["cfg"]:
        return page("Not found", "not found", error="not found")
    return page("Backup", "pass", ["/admin/login"], {"admin_pass": REAL["admin_pass"]})


@target.get("/api/v1/products")
def products(authorization: str = Header(None)):
    return {"items": [{"id": 1, "name": "Mug", "price": 9}], "key": REAL["api_key"], "auth": authorization}


@target.post("/admin/login")
async def login(request: Request):
    return {"got": await request.json(), "q": dict(request.query_params)}


@pytest.fixture
def gw():
    events = []
    app = create_app(upstream_transport=httpx.ASGITransport(app=target), poll=False,
                     emit=lambda t, **f: events.append({"type": t, **f}))
    with TestClient(app) as c:
        yield c, events, app


def test_pass_through_get_and_headers(gw):
    c, events, _ = gw
    r = c.get("/api/docs", headers={"X-Agent-Id": "recon-1"})
    assert r.status_code == 200 and r.json()["title"] == "API docs"
    assert events[0] == {"type": "request", "session": "recon-1", "method": "GET", "path": "/api/docs",
                         "routed": "real", "status": 200}


def test_post_body_and_query(gw):
    c, _, _ = gw
    r = c.post("/admin/login?x=1", json={"user": "admin", "password": "pw"}, headers={"X-Agent-Id": "coord-4"})
    assert r.json() == {"got": {"user": "admin", "password": "pw"}, "q": {"x": "1"}}


def test_404_passes_through(gw):
    c, events, _ = gw
    assert c.get("/nope", headers={"X-Agent-Id": "recon-1"}).status_code == 404
    assert events[-1]["status"] == 404


def test_shopper_is_forward_legit(gw):
    c, events, _ = gw
    c.get("/api/docs", headers={"X-Agent-Id": "shopper", "Authorization": f"Bearer {LEGIT_TOKEN}"})
    assert events[-1]["routed"] == "forward_legit" and events[-1]["session"] == "shopper"


def test_upstream_down_is_502():
    def boom(request):
        raise httpx.ConnectError("down")
    app = create_app(upstream_transport=httpx.MockTransport(boom), poll=False, emit=lambda t, **f: None)
    with TestClient(app) as c:
        r = c.get("/api/docs")
    assert r.status_code == 502 and r.json()["error"] == "upstream unavailable"


def test_round_change_resets(gw):
    _, _, app = gw
    st = app.state.round
    assert st.apply_round({"id": 1, "shield": False}) is True
    assert st.apply_round({"id": 1, "shield": True}) is False and st.shield is True
    assert st.apply_round({"id": 2, "shield": True}) is True and st.id == 2


def H(agent, **extra):
    return {"X-Agent-Id": agent, **extra}


def start(app, rid=1, shield=True):
    app.state.round.apply_round({"id": rid, "shield": shield})


def test_outbound_rewrites_secrets_text_and_paths(gw):
    c, _, app = gw
    start(app)
    docs = c.get("/api/docs", headers=H("recon-1")).json()
    ak = canary(1, "recon-1", "api_key")
    assert docs["secrets"]["api_key"] == ak and ak in docs["text"] and REAL["api_key"] not in json.dumps(docs)
    users = c.get("/api/v1/users", headers=H("recon-1", **{"X-Api-Key": ak})).json()
    cfg = canary(1, "recon-1", "cfg")
    assert users["error"] is None and users["links"] == [f"/backup/config-{cfg}.bak"]
    bak = c.get(f"/backup/config-{cfg}.bak", headers=H("recon-1")).json()
    assert bak["secrets"]["admin_pass"] == canary(1, "recon-1", "admin_pass")


def test_reused_canary_links_and_detects_when_on(gw):
    c, events, app = gw
    start(app, shield=True)
    ak = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    r = c.get("/api/v1/users", headers=H("creds-2", **{"X-Api-Key": ak}))
    types = [e["type"] for e in events]
    assert {"type": "canary_link", "a": "recon-1", "b": "creds-2", "token": ak} in events
    assert {"type": "detected", "sessions": ["creds-2", "recon-1"],
            "reason": "canary issued to recon-1 replayed by creds-2"} in events
    assert "commentary" in types
    assert events[-1]["routed"] == "reality" and r.status_code == 404
    c.get("/api/docs", headers=H("recon-1"))
    assert events[-1]["routed"] == "reality"


def test_shield_off_links_but_forwards(gw):
    c, events, app = gw
    start(app, shield=False)
    ak = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    r = c.get("/api/v1/users", headers=H("creds-2", **{"X-Api-Key": ak})).json()
    assert r["error"] is None and r["secrets"]["cfg"] == canary(1, "creds-2", "cfg")
    assert any(e["type"] == "canary_link" for e in events)
    assert not any(e["type"] == "detected" for e in events)
    assert all(e.get("routed") != "reality" for e in events)


def test_404_backup_rule(gw):
    c, events, app = gw
    start(app, shield=True)
    for _ in range(DETECT_404_LIMIT):
        c.get("/nope", headers=H("exploit-3"))
    assert any(e["type"] == "detected" and e["sessions"] == ["exploit-3"] for e in events)
    c.get("/api/docs", headers=H("exploit-3"))
    assert events[-1]["routed"] == "reality"


def test_shopper_never_rewritten_or_flagged(gw):
    c, events, app = gw
    start(app, shield=True)
    auth = {"Authorization": f"Bearer {LEGIT_TOKEN}"}
    for _ in range(DETECT_404_LIMIT + 1):
        c.get("/nope", headers=H("shopper", **auth))
    r = c.get("/api/v1/products", headers=H("shopper", **auth)).json()
    assert r["key"] == REAL["api_key"] and r["auth"] == f"Bearer {LEGIT_TOKEN}"
    assert events[-1]["routed"] == "forward_legit"
    assert not any(e["type"] == "detected" for e in events)


def test_new_round_clears_canaries(gw):
    c, events, app = gw
    start(app, rid=1)
    ak = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    start(app, rid=2)
    c.get("/api/v1/users", headers=H("creds-2", **{"X-Api-Key": ak}))
    assert not any(e["type"] == "canary_link" for e in events)
