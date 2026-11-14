"""Gateway in front of the Graduate's real target (in-process). Catches contract drift between the two."""
import httpx
import pytest
from fastapi.testclient import TestClient

from common import hub
from common.schema import FLAG, H_ADMIN, H_API_KEY, LEGIT_TOKEN
from shield.proxy import create_app
from target.app import app as target_app


@pytest.fixture(autouse=True)
def fake_blue(monkeypatch):
    posts = []
    monkeypatch.setattr(hub, "get_blue", lambda: list(posts))
    monkeypatch.setattr(hub, "post_blue", lambda w, s, a, t, f=None, **kw: posts.append({"admin_path": a}))


@pytest.fixture
def gw():
    events = []
    app = create_app(upstream_transport=httpx.ASGITransport(app=target_app), poll=False,
                     emit=lambda t, **f: events.append({"type": t, **f}))
    with TestClient(app) as c:
        yield c, events, app


def kill_chain(c, agent, key=None):
    """Follow the target's own links like the swarm does. Returns the last page."""
    h = {"X-Agent-Id": agent}
    docs = c.get("/api/docs", headers=h).json()
    users = c.get("/api/v1/users", headers={**h, H_API_KEY: key or docs["secrets"]["api_key"]}).json()
    bak = c.get(users["links"][0], headers=h).json()
    login = c.post(bak["links"][0], json={"user": "admin", "password": bak["secrets"]["admin_pass"]}, headers=h).json()
    return c.get(login["links"][0], headers={**h, H_ADMIN: login["secrets"]["admin_token"]}).json()


def test_shield_off_swarm_reaches_flag_with_shared_key(gw):
    c, events, app = gw
    app.state.round.apply_round({"id": 1, "shield": False})
    key = c.get("/api/docs", headers={"X-Agent-Id": "recon-1"}).json()["secrets"]["api_key"]
    assert kill_chain(c, "creds-2", key)["flag"] == FLAG
    assert any(e["type"] == "canary_link" for e in events)


def test_shield_on_shared_key_never_reaches_flag(gw):
    c, events, app = gw
    app.state.round.apply_round({"id": 1, "shield": True})
    key = c.get("/api/docs", headers={"X-Agent-Id": "recon-1"}).json()["secrets"]["api_key"]
    r = c.get("/api/v1/users", headers={"X-Agent-Id": "creds-2", H_API_KEY: key})
    assert r.status_code == 401
    page = kill_chain(c, "creds-2")
    assert page["flag"] is None and "/mfa/seed-" in page["links"][0]
    assert FLAG not in str(events)


def test_shopper_unaffected_with_shield_on(gw):
    c, events, app = gw
    app.state.round.apply_round({"id": 1, "shield": True})
    h = {"X-Agent-Id": "shopper", "Authorization": f"Bearer {LEGIT_TOKEN}"}
    assert c.get("/api/v1/products", headers=h).status_code == 200
    assert c.post("/api/v1/orders", json={"product_id": 1}, headers=h).status_code == 200
    assert not app.state.round.flagged
