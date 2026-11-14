import httpx
from fastapi.testclient import TestClient

from common.schema import FLAG, MAX_STEPS, RED_AGENTS, TRUST_START
from swarm.run import Agent, LocalBoard, method_for, score
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
    assert a.lone and all(v < 0.3 for v in a.trust.values())
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
