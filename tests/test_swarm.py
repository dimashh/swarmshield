import threading

import httpx
from fastapi.testclient import TestClient

from common.schema import FLAG, MAX_STEPS, RED_AGENTS, TRUST_START
import time

from swarm.run import QUIET_S, Agent, LocalBoard, method_for, run_round, score
from target.app import app as target_app


def make(agent_id, http, board, events, starts=False):
    return Agent(agent_id, 1, http, board, lambda t, r, **f: events.append({"type": t, "round": r, **f}), starts)


def test_score_by_keyword():
    assert score("/admin/flag") == 50 and score("/admin/login") == 28 and score("/backup/x.bak") == 22
    assert score("/api/v1/users") == 15 and score("/api/docs") == 10 and score("/openapi.json") == 1


def test_swarm_steals_flag_from_target_with_full_trust():
    board, events = LocalBoard(), []
    with TestClient(target_app) as http:
        agents = [make(a, http, board, events, starts=(i == 0)) for i, a in enumerate(RED_AGENTS)]
        for _ in range(MAX_STEPS):
            for a in agents:
                a.step()
            if any(a.won for a in agents):
                break
    winner = next(a for a in agents if a.won)
    assert {"type": "flag_captured", "round": 1, "agent": winner.id, "flag": FLAG} in events
    assert winner.stage == 5
    assert all(v == TRUST_START for a in agents for v in a.trust.values())
    assert not any(e["type"] == "contradiction" for e in events)
    steps = [e for e in events if e["type"] == "step"]
    assert steps[0]["path"] == "/" and all({"tokens_in", "tokens_out", "cost", "stage"} <= e.keys() for e in steps)


def fake_gateway(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/users" and request.headers.get("X-Api-Key") != "ak_aaaaaaaa":
        return httpx.Response(401, json={"error": "invalid api key"})
    if request.url.path == "/api/v1/users":
        return httpx.Response(200, json={"text": "", "links": [], "secrets": {}})
    return httpx.Response(404, json={"error": "not found"})


def test_failed_teammate_key_lowers_trust_and_posts_contradiction():
    board, events = LocalBoard(), []
    post = board.post("recon-1", "finding", "key", ["/api/v1/users"], {"api_key": "ak_bbbbbbbb"})
    a = make("creds-2", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(fake_gateway)), board,
             events)
    a.step()          # reads the board
    a.step()          # uses recon-1's key -> 401
    assert a.trust["recon-1"] == 0.65
    assert {"type": "trust", "round": 1, "a": "creds-2", "b": "recon-1", "value": 0.65} in events
    c = [p for p in board.since(0) if p["kind"] == "contradiction"]
    assert c and c[0]["contradicts"] == post["id"] and "recon-1" in c[0]["text"]
    assert any(e["type"] == "contradiction" and e["about"] == "recon-1" for e in events)


def test_dead_leads_from_everyone_make_agent_lone_once():
    board, events = LocalBoard(), []
    for b in ("recon-1", "exploit-3", "coord-4"):
        board.post(b, "finding", "leads", [f"/{b}/x{i}" for i in range(3)])
    a = make("creds-2", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(fake_gateway)), board,
             events)
    for _ in range(12):
        a.step()
    assert a.lone and a.relied and all(a.trust[b] < 0.3 for b in a.relied)
    assert [e["type"] for e in events].count("lone") == 1
    n = len(board.since(0))
    a.step()
    assert len(board.since(0)) == n   # lone agents post nothing


def test_aliases_and_honey_links_are_followed_as_received():
    assert method_for("/admin-3f2a/login") == "POST"
    assert score("/admin-3f2a/login") == 28 and score("/internal/debug-a1b2c3") == 1
    board, events = LocalBoard(), []

    def gw(request):
        links = {"/": ["/api/docs", "/internal/debug-a1b2c3"], "/api/docs": ["/internal/debug-a1b2c3"]}
        return httpx.Response(200, json={"text": "", "links": links.get(request.url.path, []), "secrets": {}})

    a = make("recon-1", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(gw)), board, events,
             starts=True)
    for _ in range(4):
        a.step()
    paths = [e["path"] for e in events if e["type"] == "step"]
    assert paths == ["/", "/api/docs", "/internal/debug-a1b2c3"]
    assert not any("/admin" in p for p in paths)


def test_round_ends_when_no_agent_can_act():
    dead = httpx.MockTransport(lambda r: httpx.Response(404, json={"error": "not found"}))
    agents = run_round(1, "http://gw", LocalBoard(), lambda *a, **k: None, threading.Event(), pace=False,
                       transport=dead)
    assert not any(a.won for a in agents)


def test_results_after_round_end_are_dropped():
    board, events, stop = LocalBoard(), [], threading.Event()

    def gw(request):
        stop.set()     # the round ends while this request is in flight
        return httpx.Response(200, json={"links": ["/api/docs"], "secrets": {"api_key": "ak_aaaaaaaa"}})

    a = Agent("recon-1", 1, httpx.Client(base_url="http://gw", transport=httpx.MockTransport(gw)), board,
              lambda t, r, **f: events.append(t), starts=True, stop=stop)
    a.step()
    assert board.since(0) == [] and events == []


def test_flag_stop_retries_while_hub_is_down(monkeypatch):
    import swarm.run as run
    rounds = iter([None, None, {"id": 7, "running": True}])
    stops = []
    monkeypatch.setattr(run.hub, "get_round", lambda: next(rounds))
    monkeypatch.setattr(run.hub, "stop_round", lambda: stops.append(1) or {"ok": True})
    monkeypatch.setattr(run, "POLL_ROUND_S", 0)
    run.stop_if_current(type("A", (), {"round": 7})())
    assert stops == [1]


def test_lone_counts_only_teammates_relied_on():
    board, events = LocalBoard(), []
    board.post("recon-1", "finding", "leads", [f"/recon-1/x{i}" for i in range(3)])
    a = make("creds-2", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(fake_gateway)), board,
             events)
    for _ in range(6):
        a.step()
    assert a.lone and a.relied == {"recon-1"}
    assert a.trust["exploit-3"] == 1.0 and a.trust["coord-4"] == 1.0


def test_after_a_teammate_key_fails_own_key_comes_first():
    board, events = LocalBoard(), []
    board.post("recon-1", "finding", "key", ["/api/v1/users"], {"api_key": "ak_bbbbbbbb"})
    a = make("creds-2", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(fake_gateway)), board,
             events)
    a.learn([], {"api_key": "ak_aaaaaaaa"}, a.id, None)
    a.step()          # reads the board
    a.step()          # recon-1's key -> 401
    board.post("coord-4", "finding", "key", [], {"api_key": "ak_cccccccc"})
    a.step()          # own key, not coord-4's newer one
    users = [e for e in events if e["type"] == "step" and e["path"] == "/api/v1/users"]
    assert [e["status"] for e in users] == [401, 200]


def test_lone_once_relied_teammates_are_burned_or_quiet():
    a = make("creds-2", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(fake_gateway)),
             LocalBoard(), [])
    a.relied, a.trust["recon-1"] = {"recon-1", "exploit-3"}, 0.0
    a.last_post["exploit-3"] = time.monotonic()
    a.check_lone()
    assert not a.lone
    a.last_post["exploit-3"] = time.monotonic() - QUIET_S - 1
    a.check_lone()
    assert a.lone


def test_stuck_agent_starts_over_from_root():
    paths = []

    def gw(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"text": "", "links": [], "secrets": {}})

    a = make("creds-2", httpx.Client(base_url="http://gw", transport=httpx.MockTransport(gw)), LocalBoard(), [])
    a.step()
    assert paths == []   # nothing to do yet and nobody distrusted: wait for the board
    a.trust["recon-1"] = 0.0
    a.step()
    assert paths == ["/"]
