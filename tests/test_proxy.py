import httpx
import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from common.schema import LEGIT_TOKEN, REAL, page
from shield.proxy import create_app

target = FastAPI()


@target.get("/api/docs")
def docs():
    return page("API docs", f"key {REAL['api_key']}", ["/api/v1/users"], {"api_key": REAL["api_key"]})


@target.get("/api/v1/users")
def users(x_api_key: str = Header(None)):
    return page("Users", "ok") if x_api_key == REAL["api_key"] else page("Users", "no", error="invalid api key")


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
    assert r.status_code == 200 and r.json()["secrets"] == {"api_key": REAL["api_key"]}
    assert c.get("/api/v1/users", headers={"X-Agent-Id": "recon-1", "X-Api-Key": REAL["api_key"]}).json()["error"] is None
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
