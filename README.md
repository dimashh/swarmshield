# SwarmShield Split-Brain

Attacker swarms win because they share what they find. SwarmShield is a blue swarm that gives every attacker its own slightly different reality, so the more the red agents share, the more they contradict each other, until they stop trusting each other and fall apart.

Local, sandboxed hackathon demo: toy target, scripted red agents and synthetic data only.

| Doc | What |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | One line per commit; pull before you push |
| [docs/PLAN.md](docs/PLAN.md) | Ownership, work split, timeline, demo script, prior art |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Interfaces everyone builds against (wins over PLAN §2) |
| [docs/FLOWS.md](docs/FLOWS.md) | Flows as text diagrams |
| [docs/COMPETITOR_RESEARCH.md](docs/COMPETITOR_RESEARCH.md) | Competitor and prior-art research |
| [docs/flows.html](docs/flows.html) | Flows as pictures (download and open in a browser) |
| [common/schema.py](common/schema.py) | Shared constants and helpers (`python common/schema.py` self-checks) |
| [common/hub.py](common/hub.py) | Hub client: `get_round`, board/blue helpers, non-blocking `emit` |
| [hub/static/mock_state.json](hub/static/mock_state.json) | Example `/api/state` for building the dashboard |

## Owners
- Senior: `shield/`, `common/`
- Graduate: `target/`, `swarm/`
- Product: `hub/`

## Run (once built)
```
uvicorn target.app:app --port 9000
uvicorn shield.proxy:app --port 8080
uvicorn hub.app:app --port 8000
python -m swarm.run
```
Then open http://localhost:8000.

Tests: `pip install -r requirements-dev.txt && python -m pytest tests`
