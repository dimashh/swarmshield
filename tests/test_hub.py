import pytest
from fastapi.testclient import TestClient

from hub import app as hub

c = TestClient(hub.app)


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "EVENTS_LOG", tmp_path / "events.jsonl")


def test_round_ids_continue_from_log(tmp_path):
    (tmp_path / "events.jsonl").write_text('{"type": "step", "round": 7}\nnot json\n')
    assert hub._last_logged_round() == 7


def test_flag_event_after_stop_counts_for_that_round():
    c.post("/api/reset")
    rid = c.post("/api/round/off").json()["id"]
    c.post("/api/events", json={"type": "step", "round": rid, "agent": "coord-4", "path": "/", "status": 200, "stage": 4})
    c.post("/api/round/stop", params={"round": rid})
    c.post("/api/events", json={"type": "flag_captured", "round": rid, "agent": "coord-4", "flag": "FLAG{x}"})
    s = c.get("/api/state").json()
    assert s["captured_by"] == "coord-4"
    assert s["results"][-1]["flag"] is True and s["results"][-1]["time_to_flag"] is not None


def test_late_non_flag_events_do_not_change_result():
    c.post("/api/reset")
    rid = c.post("/api/round/on").json()["id"]
    c.post("/api/round/stop", params={"round": rid})
    c.post("/api/events", json={"type": "contradiction", "round": rid, "agent": "recon-1", "about": "creds-2"})
    assert c.get("/api/state").json()["results"][-1]["contradictions"] == 0


def test_round_id_survives_restart_before_first_event():
    rid = c.post("/api/round/on").json()["id"]
    assert hub._last_logged_round() == rid
