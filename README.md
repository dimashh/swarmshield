# SwarmShield Split-Brain

Attacker swarms win because they share what they find. SwarmShield is a gateway with its own blue swarm: a **Sentinel** that spots attackers working as a team, and one **Warden** per caught attacker that serves it a private, consistent fake API. The more the red agents share, the more they contradict each other, until they stop trusting each other and fall apart. Real customers keep using the real API untouched.

> Local, sandboxed hackathon demo: a toy target, scripted red agents and synthetic secrets only. Nothing here attacks a real system. Known limits are listed in [docs/WORTH_CALLING_OUT.md](docs/WORTH_CALLING_OUT.md); read them before presenting.

## Quick start

Needs Python 3.9 or newer and a bash shell (macOS/Linux; on Windows use WSL or Git Bash).

```bash
gh repo clone dimashh/swarmshield && cd swarmshield     # private repo: log in first (gh auth login)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run_demo.sh                                           # hub :8000, target :9000, gateway :8080, swarm + shopper
```

Open **http://127.0.0.1:8000** and press `2` (Shield ON) or `1` (Shield OFF). Ctrl-C in the terminal stops everything; service logs are in `logs/`.

After `git pull`, always restart `./run_demo.sh` and hard-refresh the dashboard (Cmd/Ctrl+Shift+R).

## Dashboard

| Key | Action |
|---|---|
| `1` | New round, Shield OFF |
| `2` | New round, Shield ON |
| `N` or → | Next stage (step mode) |
| `P` or space | Pause / resume |
| `A` | Switch step mode ↔ auto (remembered per browser) |
| `E` | End the round (shows the result banner and OFF vs ON scorecard) |
| `X` | Reset everything, including the scorecard |

- **Step mode (default):** the round pauses as each stage begins; press `N` to move on. Only what belongs to the current stage is shown. **Auto:** runs straight through.
- **Left, API view:** attackers (left) and the real customer (bottom) send requests through the SwarmShield gateway (Sentinel on top) to the real API's endpoints. Red dots: attackers hitting the real API. Green: the real customer. When an attacker is caught, its Warden appears as a fake API and the attacker's requests (orange) and marker move inside it. ✗ = a teammate's value rejected.
- **Right:** swarm detection (trust graph; blue dashed arrows = "used a teammate's key") and a plain-words Warden activity feed.
- **Bottom:** prize, time to spot the swarm, Wardens spawned, shared tips that failed, attackers gone alone, real-customer requests OK, attacker $ burned vs defence $ (illustrative, scaled ×10,000).
- **Stages (Shield ON):** 1 attackers hit the API → 2 Sentinel spots the swarm → 3 Wardens spawn fake APIs → 4 shared tips start failing → 5 the swarm falls apart.
- `?mock=1` shows `hub/static/mock_state.json` instead of live data. With only the hub running, `python -m hub.fake_round both` plays a scripted OFF then ON round (backup demo).

**Typical live numbers** (this machine; they vary run to run): Shield OFF, the prize is stolen in about 15s. Shield ON, the swarm is spotted in about 6-8s, all 4 attackers are moved to Wardens, 0 real-API hits after detection, the real customer stays at 100%. All 4 attackers go alone, most within a few seconds of detection and the last by about 20-25s of round time; the dashboard shows them one at a time.

## How it works

```text
 red swarm (4 agents) ─┐                            ┌───────────────────────────────┐
                       ├── HTTP, X-Agent-Id ──> GATEWAY :8080  Sentinel + Wardens    │── unflagged only ──> TARGET :9000
 real customer ────────┘   (Bearer token)       │  canaries, aliases, honey links    │                       (toy shop API)
                                                └──────────────┬────────────────────┘
          red board, trust/step events                         │ events, blue board posts
                       └──────────────> HUB :8000 <────────────┘ ── GET /api/state every 300ms ──> DASHBOARD
```

1. **Canaries.** Every attacker session is shown its own copy of every secret (`ak_…`, `cfg_…`, `pw_…`, `adm_…`) and its own admin path (`/admin-xxxx`). Copies rotate every 20s; old copies still work for their owner. Copies are swapped back to the real values before forwarding, so the target sees normal traffic.
2. **Sentinel** (`shield/sentinel.py`) flags a session when it: uses a copy issued to another session (the swarm is sharing), opens a bait link (`/internal/debug-…`, one per session, Shield ON only), goes straight to the unpublished `/admin`, sends more than 10 requests in 2s, or hits 5 dead routes. Each alert is posted to the blue board.
3. **Wardens** (`shield/wardens.py`). Each flagged session gets its own fake world: its own key, config, password, token and admin path (no two Wardens share one, coordinated via the blue board), and an endless "prize moved" chain instead of the flag. Anything from another attacker's world, or a real value, gets a believable 401/403/404. Flagged sessions never reach the real target again.
4. **Trust collapse** (the swarm side, `swarm/run.py`). Each failed teammate tip lowers trust; an agent that distrusts every teammate it relied on goes **alone** and stops sharing.
5. **Real customer.** Requests with `Authorization: Bearer legit-shopper-token` bypass detection and rewriting and go straight to the real API.

| Service | Port | Owner | Run on its own |
|---|---|---|---|
| Target (toy shop API) | 9000 | Graduate | `uvicorn target.app:app --port 9000` |
| Gateway: Sentinel + Wardens | 8080 | Senior | `uvicorn shield.proxy:app --port 8080` |
| Hub + dashboard | 8000 | Product | `uvicorn hub.app:app --port 8000` |
| Red swarm + real customer | – | Graduate | `python -m swarm.run` |

The hub's API (rounds, pause, red/blue boards, events, `/api/state`) and every event type are in [docs/CONTRACTS.md](docs/CONTRACTS.md). `run_demo.sh` falls back to the stand-in hub `shield/stubhub.py` if `hub/app.py` is missing.

## Tests and rehearsal

```bash
pip install -r requirements-dev.txt
python -m pytest tests            # gateway, Wardens, hub, swarm, shopper, gateway + real target
python -m shield.rehearse         # scripted swarm through the gateway: detect time, real hits, shopper %
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Repository not found` on clone | Private repo: `gh auth login`, then `gh repo clone dimashh/swarmshield` |
| `command not found: python` | Use `python3` to create the venv; inside it `python` works |
| `No module named uvicorn` | `pip install -r requirements.txt` inside the venv |
| `port 8080 already in use` | `lsof -ti :8080 \| xargs kill`, then `./run_demo.sh` |
| `hub failed to start, see logs/hub.log` | Read `logs/hub.log`; usually a missing package or an old Python |
| Dashboard shows **HUB IS OUTDATED** or doesn't pause | Restart `./run_demo.sh` after pulling, then hard-refresh |
| Round pauses but nothing moves after `N` | Close other dashboard tabs; each tab in step mode pauses the round |

## Docs

| Doc | What |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | One line per commit, newest first |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Interfaces everyone builds against (wins over PLAN) |
| [docs/PLAN.md](docs/PLAN.md) | Ownership, work split, timeline, demo script, prior art |
| [docs/FLOWS.md](docs/FLOWS.md) / [docs/flows.html](docs/flows.html) | Flows as text diagrams / pictures |
| [docs/PRESENTATION_MATERIAL.md](docs/PRESENTATION_MATERIAL.md) | Pitch, problem-statement sources (Transluce report), Q&A |
| [docs/WORTH_CALLING_OUT.md](docs/WORTH_CALLING_OUT.md) | Known gaps and simplifications, for the slides |
| [docs/COMPETITOR_RESEARCH.md](docs/COMPETITOR_RESEARCH.md) | Competitor and prior-art research |
| [common/schema.py](common/schema.py) / [common/hub.py](common/hub.py) | Shared constants and helpers / hub client |

## Team and workflow

- **Senior:** `shield/`, `common/`. **Graduate:** `target/`, `swarm/`. **Product:** `hub/`.
- Commit straight to `main`. Run `git pull --rebase origin main` before you start and before every push, and add one line to `CHANGELOG.md` per commit.
- Changes to `common/` or `docs/CONTRACTS.md` affect everyone: tell the other owners.
- Keep code Python 3.9 compatible (no `X | None` annotations, no `match`).
