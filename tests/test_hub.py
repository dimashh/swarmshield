import time

from fastapi.testclient import TestClient

from hub import app as hub_app

c = TestClient(hub_app.app)


def _ev(**e):
    e.setdefault("round", hub_app.R.id)
    c.post("/api/events", json=e)


def setup_function():
    c.post("/api/reset")


def test_pause_freezes_the_clock():
    c.post("/api/round/on")
    time.sleep(0.15)
    assert c.post("/api/round/toggle").json()["paused"] is True
    t0 = c.get("/api/round").json()
    time.sleep(0.25)
    t1 = c.get("/api/round").json()
    assert t0["paused"] and t1["t"] == t0["t"]
    assert c.post("/api/round/resume").json()["paused"] is False
    assert c.get("/api/state").json()["paused"] is False


def test_late_flag_after_stop_still_counts():
    c.post("/api/round/off")
    c.post("/api/round/stop")
    _ev(type="flag_captured", agent="recon-1", flag="FLAG{x}")
    s = c.get("/api/state").json()
    assert s["captured_by"] == "recon-1" and s["results"][-1]["flag"] is True


def test_legit_pct_is_none_without_shopper_traffic():
    c.post("/api/round/on")
    assert c.get("/api/state").json()["legit_pct"] is None
    _ev(type="legit", method="GET", path="/api/v1/products", status=200)
    assert c.get("/api/state").json()["legit_pct"] == 100


def test_agent_timeline_bait_and_counters():
    c.post("/api/round/on")
    _ev(type="request", session="recon-1", method="GET", path="/", routed="real", status=200,
        bait={"api_key": "ak_1", "admin_path": "/admin-1234", "honey": "/internal/debug-abcdef"})
    _ev(type="detected", sessions=["recon-1", "creds-2"], reason="canary reuse")
    _ev(type="warden_block", session="recon-1", item="ak_2", status=401, **{"from": "creds-2"})
    _ev(type="contradiction", agent="recon-1", about="creds-2", post_id=1, text="no")
    _ev(type="lone", agent="recon-1")
    a = {x["id"]: x for x in c.get("/api/state").json()["agents"]}["recon-1"]
    assert a["bait"]["honey"] == "/internal/debug-abcdef" and a["caught_for"] == "canary reuse"
    assert a["flagged_at"] is not None and a["lone_at"] is not None
    assert a["rejected"] == 1 and a["complaints"] == 1
