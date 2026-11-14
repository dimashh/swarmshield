import json

import httpx
import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from common import hub
from common.schema import DETECT_404_LIMIT, LEGIT_TOKEN, RATE_LIMIT, REAL, ROTATE_S, canary, page
from shield import canary as canary_mod
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


@pytest.fixture(autouse=True)
def fake_blue(monkeypatch):
    posts = []
    monkeypatch.setattr(hub, "get_blue", lambda: list(posts))
    monkeypatch.setattr(hub, "post_blue", lambda warden, session, admin_path, text, facts=None: posts.append(
        {"warden": warden, "session": session, "admin_path": admin_path, "text": text}))
    return posts


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
    assert users["error"] is None and users["links"][0] == f"/backup/config-{cfg}.bak"
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
    assert events[-1]["routed"] == "reality" and r.status_code == 401 and r.json()["error"] == "invalid api key"
    assert {"type": "warden_block", "session": "creds-2", "item": ak, "from": "recon-1", "status": 401} in events
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


def _detect(c, app):
    start(app, shield=True)
    ak = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    c.get("/api/v1/users", headers=H("creds-2", **{"X-Api-Key": ak}))
    return ak


def _walk(c, agent, key=None):
    """Follow one session's own reality to the end. Returns the pages seen."""
    docs = c.get("/api/docs", headers=H(agent)).json()
    key = key or docs["secrets"]["api_key"]
    users = c.get("/api/v1/users", headers=H(agent, **{"X-Api-Key": key})).json()
    bak = c.get(users["links"][0], headers=H(agent)).json()
    login = c.post(bak["links"][0], json={"user": "admin", "password": bak["secrets"]["admin_pass"]},
                   headers=H(agent)).json()
    flag = c.get(login["links"][0], headers=H(agent, **{"X-Admin-Token": login["secrets"]["admin_token"]})).json()
    hint = c.get(flag["links"][0], headers=H(agent)).json()
    return docs, users, bak, login, flag, hint


def test_reality_is_consistent_and_never_gives_flag(gw, fake_blue):
    c, events, app = gw
    _detect(c, app)
    docs, users, bak, login, flag, hint = _walk(c, "creds-2")
    w = app.state.round.wardens["creds-2"]
    adm = w.facts["admin_path"]
    assert docs["secrets"]["api_key"] == w.facts["api_key"]
    assert bak["links"] == [f"{adm}/login"] and login["links"] == [f"{adm}/flag"]
    assert flag["flag"] is None and flag["links"] == [w.facts["flag_hint"]] and "migrated" in flag["text"]
    assert hint["flag"] is None and hint["links"][0].startswith(f"{adm}/mfa/seed-")
    assert not any(e["type"] == "request" and e["session"] in ("recon-1", "creds-2") and e["routed"] == "real"
                   and events.index(e) > next(i for i, x in enumerate(events) if x["type"] == "detected")
                   for e in events)
    assert any(e["type"] == "reality_assigned" and e["session"] == "creds-2" and e["facts"]["admin_path"] == adm
               for e in events)
    assert any(e["type"] == "defender_cost" for e in events)


def test_own_pre_flag_canary_still_works(gw):
    c, _, app = gw
    ak = _detect(c, app)
    users = c.get("/api/v1/users", headers=H("recon-1", **{"X-Api-Key": ak}))
    assert users.status_code == 200 and users.json()["error"] is None


def test_realities_differ_and_cross_reality_fails(gw, fake_blue):
    c, events, app = gw
    _detect(c, app)
    wardens = app.state.round.wardens
    assert wardens["recon-1"].facts["admin_path"] != wardens["creds-2"].facts["admin_path"]
    assert {p["admin_path"] for p in fake_blue if p["warden"] != "Sentinel"} == \
        {w.facts["admin_path"] for w in wardens.values()}
    r_docs, _, r_bak, r_login, _, _ = _walk(c, "recon-1")
    r = c.post(r_bak["links"][0], json={"user": "admin", "password": r_bak["secrets"]["admin_pass"]},
               headers=H("creds-2"))
    assert r.status_code == 404
    assert events[-1] == {"type": "request", "session": "creds-2", "method": "POST", "path": r_bak["links"][0],
                          "routed": "reality", "status": 404}
    assert any(e["type"] == "warden_block" and e["from"] == "recon-1" for e in events)
    r = c.get("/api/v1/users", headers=H("creds-2", **{"X-Api-Key": r_docs["secrets"]["api_key"]}))
    assert r.status_code == 401


def test_real_admin_path_blocked_for_flagged(gw):
    c, events, app = gw
    _detect(c, app)
    r = c.post("/admin/login", json={"user": "admin", "password": REAL["admin_pass"]}, headers=H("creds-2"))
    assert r.status_code == 404
    assert events[-2]["type"] == "warden_block" and events[-2]["from"] == "real"


def _to_backup(c, agent):
    ak = c.get("/api/docs", headers=H(agent)).json()["secrets"]["api_key"]
    users = c.get("/api/v1/users", headers=H(agent, **{"X-Api-Key": ak})).json()
    return c.get(users["links"][0], headers=H(agent)).json()


def test_admin_path_is_aliased_per_session_and_swapped_back(gw):
    c, events, app = gw
    start(app, shield=False)
    bak = _to_backup(c, "recon-1")
    login = bak["links"][0]
    assert login.startswith("/admin-") and login.endswith("/login") and "/admin/" not in json.dumps(bak)
    assert login != _to_backup(c, "creds-2")["links"][0]
    r = c.post(login, json={"user": "admin", "password": "pw"}, headers=H("recon-1")).json()
    assert r["got"] == {"user": "admin", "password": "pw"}
    assert not any(e["type"] == "canary_link" for e in events)


def test_reused_alias_links_sessions(gw):
    c, events, app = gw
    start(app, shield=True)
    login = _to_backup(c, "recon-1")["links"][0]
    r = c.post(login, json={"user": "admin", "password": "x"}, headers=H("exploit-3"))
    assert any(e["type"] == "canary_link" and e["a"] == "recon-1" and e["b"] == "exploit-3" for e in events)
    assert r.status_code == 404 and events[-1]["routed"] == "reality"


def test_copies_rotate_but_old_ones_keep_working_for_owner(gw):
    c, events, app = gw
    start(app, shield=True)
    old = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    app.state.round.started -= ROTATE_S
    new = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    assert old != new and new == canary(1, "recon-1@1", "api_key")
    for key in (old, new):
        assert c.get("/api/v1/users", headers=H("recon-1", **{"X-Api-Key": key})).json()["error"] is None
    assert not any(e["type"] in ("canary_link", "detected") for e in events)


def test_honey_link_only_when_on_and_flags_visitor(gw):
    c, events, app = gw
    start(app, shield=False)
    links = c.get("/api/docs", headers=H("recon-1")).json()["links"]
    assert not any(link.startswith(canary_mod.HONEY_PREFIX) for link in links)
    start(app, rid=2, shield=True)
    honey = c.get("/api/docs", headers=H("recon-1")).json()["links"][-1]
    assert honey.startswith(canary_mod.HONEY_PREFIX)
    r = c.get(honey, headers=H("recon-1"))
    assert r.status_code == 404 and events[-1]["routed"] == "reality"
    assert any(e["type"] == "detected" and e["sessions"] == ["recon-1"] and "honey" in e["reason"] for e in events)


def test_teammate_on_honey_link_is_linked(gw):
    c, events, app = gw
    start(app, shield=True)
    honey = c.get("/api/docs", headers=H("recon-1")).json()["links"][-1]
    c.get(honey, headers=H("coord-4"))
    assert {"recon-1", "coord-4"} <= app.state.round.flagged


def test_unpublished_real_admin_flags_when_on(gw):
    c, events, app = gw
    start(app, shield=True)
    r = c.post("/admin/login", json={"user": "admin", "password": "x"}, headers=H("exploit-3"))
    assert r.status_code == 404 and "exploit-3" in app.state.round.flagged
    start(app, rid=2, shield=False)
    r = c.post("/admin/login", json={"user": "admin", "password": "x"}, headers=H("exploit-3"))
    assert r.status_code == 200 and "exploit-3" not in app.state.round.flagged


def test_rate_limit_flags_scripted_session_not_shopper(gw):
    c, events, app = gw
    start(app, shield=True)
    for _ in range(RATE_LIMIT + 1):
        c.get("/api/docs", headers=H("shopper", Authorization=f"Bearer {LEGIT_TOKEN}"))
        c.get("/api/docs", headers=H("exploit-3"))
    assert app.state.round.flagged == {"exploit-3"}
    assert any(e["type"] == "detected" and "requests in" in e["reason"] for e in events)


def test_own_pre_flag_alias_maps_into_reality(gw):
    c, _, app = gw
    start(app, shield=True)
    bak = _to_backup(c, "recon-1")
    detect_ak = c.get("/api/docs", headers=H("recon-1")).json()["secrets"]["api_key"]
    c.get("/api/v1/users", headers=H("creds-2", **{"X-Api-Key": detect_ak}))
    adm = app.state.round.wardens["recon-1"].facts["admin_path"]
    r = c.post(bak["links"][0], json={"user": "admin", "password": bak["secrets"]["admin_pass"]}, headers=H("recon-1"))
    assert r.status_code == 200 and r.json()["links"] == [f"{adm}/flag"]


def test_sentinel_posts_alert_to_blue_board_before_wardens(gw, fake_blue):
    c, events, app = gw
    _detect(c, app)
    assert fake_blue[0]["warden"] == "Sentinel" and fake_blue[0]["admin_path"] is None
    assert fake_blue[0]["session"] == "creds-2, recon-1" and "recon-1 replayed by creds-2" in fake_blue[0]["text"]
    assert [p["warden"] for p in fake_blue[1:]] == ["W-creds-2", "W-recon-1"]
    assert any(e["type"] == "commentary" and e["text"].startswith("Sentinel: ") for e in events)
