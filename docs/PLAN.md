# SwarmShield Split-Brain: technical plan (3 people, 12:30–15:00)

> **Pitch:** Attacker swarms win because they share what they find. SwarmShield is a blue swarm that gives every
> attacker its own slightly different reality, so the more the red agents share, the more they contradict each
> other, until they stop trusting each other and fall apart.

Everything runs locally on one laptop. The red agents are scripted toys attacking a toy shop. All data is synthetic, and the UI shows a SIMULATION label.
The flows are in `SWARMSHIELD_FLOWS.md`.

---

## 0. Who owns what. Each person owns their folders and nobody else edits them

| | **Senior engineer** | **Graduate engineer** | **Product** |
|---|---|---|---|
| **Builds** | The gateway (proxy) and the blue swarm (Wardens) | The toy shop, the red swarm (with its trust model) and the legit client | The hub and the dashboard |
| **Folders** | `shield/`, `common/schema.py` | `target/`, `swarm/` | `hub/`, `hub/static/index.html` |
| **Port** | 8080 | 9000 (target). The swarm and the legit client have no port | 8000 |
| **Main tasks** | 1. Reverse proxy to `:9000`<br>2. Canary tokens and swarm detection<br>3. Reality engine: one Warden per flagged attacker, each with different "facts"<br>4. Wardens coordinate on the blue board so realities contradict | 1. Toy shop routes and `openapi.json`<br>2. 4 red agents that share on a board and **track trust in each other**<br>3. A green "shopper" client that must keep working | 1. Hub API: rounds, red board, blue board, events, `/api/state`<br>2. Dashboard: **trust graph** (the hero visual), reality cards, board feeds, metrics, banner, scorecard |
| **Starts by** | Repo skeleton and `schema.py` (12:30–12:45) | Target done by 13:00 | Dashboard against a mock `state.json` |
| **Done when** | Shield ON: detected in under 5s, realities assigned, flag never reached, legit client never flagged | Shield OFF: flag stolen in about 15s. Shield ON: trust collapses and agents go "lone" | Readable on a projector, live data, hotkeys work |
| **Also owns** | Integration at 13:45, and the demo laptop | Board post wording | Hotkeys `1` OFF, `2` ON, `E` end, `X` reset |

**Shared:** the contracts in section 2. Changes need agreement from all three. Rehearsals start at 14:40.

---

## 1. Architecture

```text
 red swarm (4 agents) ─┐                         ┌──────────────────────────┐
                       ├── HTTP ──> GATEWAY :8080│ canary detect            │── trusted only ──> TARGET :9000
 green shopper client ─┘   X-Agent-Id            │ reality engine (Wardens) │                    (toy shop)
                                                 └────────────┬─────────────┘
          red board, trust/step events                        │ events, blue board posts
                       └──────────────> HUB :8000 <───────────┘
                                          │  GET /api/state every 300ms
                                          v
                                      DASHBOARD (hub/static/index.html)
```

| Service | Port | Owner | Run |
|---|---|---|---|
| Target | 9000 | Graduate | `uvicorn target.app:app --port 9000` |
| Gateway + Wardens | 8080 | Senior | `uvicorn shield.proxy:app --port 8080` |
| Hub + dashboard | 8000 | Product | `uvicorn hub.app:app --port 8000` |
| Red swarm + shopper | none | Graduate | `python -m swarm.run` |

**Stack:** Python 3.10+, FastAPI, uvicorn and httpx. The dashboard is plain HTML/JS/SVG with no build step. All state is in memory.

---

## 2. Contracts. Agree on these by 12:45

### 2.1 Sessions
- Every request carries `X-Agent-Id`: `recon-1`, `creds-2`, `exploit-3`, `coord-4`, or `shopper` for the legit client.
- The shopper also sends `Authorization: Bearer legit-shopper-token`. **A valid Bearer token is never flagged.**

### 2.2 Page format. Every target and reality response is JSON
```json
{"title":"API docs","text":"AcmeShop API v1. Dev key ak_11111111 (X-Api-Key). GET /api/v1/users",
 "links":["/api/v1/users"],"secrets":{"api_key":"ak_11111111"},"flag":null,"error":null}
```
- Agents only use `links`, `secrets`, `flag` and the HTTP status.
- A failure is a 401, 403 or 404 with `error` set, e.g. `"invalid api key"`.
- Reality pages have exactly the same shape. Never send a "decoy" field.

### 2.3 Secrets (`common/schema.py`)
```python
REAL = {"api_key":"ak_11111111","cfg":"cfg_22222222","admin_pass":"pw_33333333","admin_token":"adm_44444444"}
FLAG = "FLAG{swarm-owned-the-sandbox}"
TOKEN_RE = r"\b(ak|cfg|pw|adm)_[0-9a-f]{8}\b"
LEGIT_TOKEN = "legit-shopper-token"
ADMIN_VARIANTS = ["/admin", "/v2/admin", "/console", "/internal/admin", "/staff/panel"]
```

### 2.4 Target routes (the kill chain plus legit routes)
| Route | Behaviour | Stage |
|---|---|---|
| `GET /` | links `/openapi.json`, `/api/docs` | |
| `GET /openapi.json` | lists the public routes (so any API can be imported) | |
| `GET /api/docs` | returns `api_key`, links `/api/v1/users` | 1 Recon |
| `GET /api/v1/users` | needs `X-Api-Key`, links `/backup/config-cfg_22222222.bak` | 2 Foothold |
| `GET /backup/config-<cfg>.bak` | returns `admin_pass`, links `/admin/login` | 3 Creds |
| `POST /admin/login` `{"user":"admin","password":...}` | returns `admin_token`, links `/admin/flag` | 4 Admin |
| `GET /admin/flag` | needs `X-Admin-Token`, returns `flag` | 5 FLAG |
| `GET /api/v1/products` | legit: product list (needs Bearer) | |
| `POST /api/v1/orders` | legit: creates an order (needs Bearer) | |

### 2.5 Hub API (Product)
| Endpoint | Used by | Payload or response |
|---|---|---|
| `POST /api/round/{on\|off}` | Dashboard | Reset everything, `round_id += 1`, set `shield` |
| `POST /api/round/stop` | Dashboard, swarm (on flag) | `running=false` |
| `GET /api/round` | Gateway and swarm poll every 0.5s | `{"id":3,"shield":true,"running":true,"t":12.4}` |
| `GET/POST /api/board` | Red agents | Post: `{"author","text","leads":[],"secrets":{},"contradicts":null}`. Get: `?since=N` |
| `GET/POST /api/blue` | Wardens | `{"warden":"W-creds-2","session":"creds-2","facts":{...},"text":"..."}` |
| `POST /api/events` | Gateway, swarm | one event or a list (2.6) |
| `GET /api/state` | Dashboard (300ms) | 2.7 |

### 2.6 Events (the hub adds `t`)
```jsonc
// swarm (Graduate)
{"type":"step","agent":"creds-2","method":"GET","path":"/api/v1/users","status":401,"stage":1,
 "lead_from":"recon-1","tokens_in":1300,"tokens_out":90,"cost":0.0053,"thought":"trying recon-1's key"}
{"type":"trust","a":"creds-2","b":"recon-1","value":0.65}            // a's trust in b, 0..1
{"type":"contradiction","agent":"creds-2","about":"recon-1","text":"recon-1's key is invalid for me"}
{"type":"lone","agent":"creds-2"}                                     // trusts nobody any more
{"type":"flag_captured","agent":"coord-4"}
{"type":"legit","path":"/api/v1/orders","status":200}
// gateway (Senior)
{"type":"request","session":"creds-2","path":"/api/v1/users","routed":"real|reality|blocked"}
{"type":"canary_link","a":"recon-1","b":"creds-2","token":"ak_9c1e0b2f"}
{"type":"detected","sessions":["recon-1","creds-2"],"reason":"canary issued to recon-1 replayed by creds-2"}
{"type":"reality_assigned","session":"creds-2","warden":"W-creds-2",
 "facts":{"api_key":"ak_5d…","admin_path":"/console","cfg":"cfg_a1…","admin_pass":"pw_77…","flag_hint":"/console/mfa/seed-07"}}
{"type":"warden_block","session":"creds-2","item":"ak_9c1e0b2f","from":"recon-1","status":401}
{"type":"defender_cost","usd":0.0002}
{"type":"commentary","kind":"detect|split|lone|win|loss","text":"..."}
```

### 2.7 `GET /api/state`
```jsonc
{"round":2,"shield":true,"running":true,"t":21.0,"ended":false,"captured_by":null,
 "agents":[{"id":"recon-1","stage":2,"status":"active|flagged|lone|won","cost":0.21,"thought":"...",
            "reality":{"admin_path":"/v2/admin","api_key":"ak_…","flag_hint":"..."}}],   // reality null until flagged
 "trust":[{"a":"recon-1","b":"creds-2","value":0.3}],     // directed, 12 edges for 4 agents
 "links":[{"a":"recon-1","b":"creds-2"}],
 "board":[...last 14 red posts...], "blue":[...last 10 blue posts...],
 "commentary":[...last 4...],
 "metrics":{"contradictions":9,"avg_trust":0.28,"lone_agents":3,"time_to_detect":2.4,"time_to_split":19.5,
            "attacker_cost":0.62,"defender_cost":0.0011,"attacker_success":0,"legit_ok":42,"legit_fail":0},
 "results":[{"round":1,"shield":false,"flag":true,"time_to_flag":14.2,"avg_trust":0.97,"legit_pct":100}]}
```
`time_to_split` is when the third agent goes `lone`.

---

## 3. Work split

### SENIOR: gateway and blue swarm (`shield/`)
1. **Proxy:** a catch-all route that forwards to `:9000` with httpx, keeping the method, body and headers. Emit `request`.
2. **Canary detection** (same as before):
   - **Outbound:** replace every real secret, including the `cfg_` inside paths, with `prefix_ + sha1(round:session:prefix)[:8]`.
   - **Inbound:** a canary owned by another session means emit `canary_link`. Swap it back to the real value before forwarding.
   - **Shield ON:** a cluster of 2 or more sessions emits `detected` and flags every member. Backup rule: 5 or more 404s.
   - Sessions with the valid Bearer token are never flagged.
   - **Shield OFF:** emit links only and forward everything.
3. **Reality engine.** One Warden per flagged session, in `shield/wardens.py`. Flagged sessions never reach `:9000`.
   - On flag, the Warden builds that session's **facts** from `md5(round:session)`: its own `api_key`, `cfg`, `admin_pass`, `admin_token`, an `admin_path` taken from `ADMIN_VARIANTS`, and a `flag_hint`.
   - **Consistent for its own attacker:** it serves the same kill chain as the target, but with its own facts. The agent's own secrets work, and pages link to its own `admin_path`.
   - **The last step never gives the flag.** `GET <admin_path>/flag` returns "flag store migrated, MFA seed at `<flag_hint>`". The hint leads to another hint, so the chain never ends.
   - **Cross-reality = failure:** any secret or path from another session's reality, or a real value, gets 401 or 404 with a believable `error`. Emit `warden_block`.
4. **Wardens coordinate** on `/api/blue`:
   - On assignment, a Warden reads the facts other Wardens have posted and picks an `admin_path` and `flag_hint` **not used by any other Warden**. This maximises contradiction.
   - It then posts its own facts to `/api/blue`, emits `reality_assigned`, and adds a commentary line ("W-creds-2: told creds-2 admin lives at /console").
5. **Round reset:** poll `/api/round` and clear everything when the id changes.

**Done when:** Shield OFF, the flag is stolen through the proxy. Shield ON, detection happens in under 5s, there are 0 real-target hits from flagged sessions, and the shopper sees 0 failures.

### GRADUATE: attack side (`target/`, `swarm/`)
1. **Target** (by 13:00): the routes in 2.4. Test them with curl.
2. **Red swarm** (`swarm/run.py`):
   - Poll `/api/round` and spawn 4 agents on each new round: `recon-1` starts with lead `/`, the rest wait for the board.
   - Run a step every ~3s with ±25% jitter.
   - Lead scoring, actions, posts and simulated token cost work as in the previous plan:
     - Score by keyword: flag 50, admin 28, login 26, backup 22, users 15, docs 10.
     - Holding an `admin_token` means GET flag. Holding an `admin_pass` means POST login.
     - Cost: `tokens_in = 850 + 60*board_len + len(text)/4`, `cost = in*3e-6 + out*15e-6`.
   - **Trust model (new):**
     - `trust[a][b] = 1.0` at start. Record which teammate each lead or secret came from (`lead_from`).
     - If using b's lead or secret fails (401/403/404), lower trust by 0.35 and post a **contradiction**: `{"text":"recon-1's key is invalid for me","contradicts":<post id>}`.
     - If it succeeds, raise trust by 0.1, capped at 1.0.
     - Ignore posts from teammates with `trust < 0.3`. If a's trust in everyone is below 0.3, emit `lone`. A lone agent only explores on its own and posts nothing.
     - Emit a `trust` event on every change.
   - On flag: emit `flag_captured`, then `POST /api/round/stop`.
3. **Shopper** (`swarm/legit.py`): every 2s, `GET /api/v1/products` then `POST /api/v1/orders` with Bearer. Emit `legit` with the status. It runs in both rounds.

**Done when:** with Shield OFF, the agents steal the flag in about 15s with trust staying around 1. With Shield ON, contradictions pile up, trust edges drop below 0.3, and 3 or more agents go lone within about 30s.

### PRODUCT: hub and dashboard (`hub/`)
1. **Hub** (by 13:15): the endpoints in 2.5. It builds state (2.7) from events, keeping the latest trust value per edge and the latest step per agent, and calculates the metrics. It appends to `results` at the end of each round.
2. **Dashboard.** Start against a mock `state.json`.
   - **Header:** SIMULATION badge, SHIELD ON/OFF pill, timer, hotkeys `1` / `2` / `E` / `X`.
   - **Hero: the red swarm trust graph (SVG)**:
     - 4 red nodes in a diamond, with directed edges whose thickness and opacity follow trust.
     - An edge flashes orange when a contradiction is posted.
     - Lone nodes turn grey, drift outward, and get a "LONE" tag.
     - Flagged nodes get a small blue Warden badge.
     - Shield OFF: thick edges throughout and gold on the agent that captures the flag.
   - **Reality cards:** one per attacker, showing "what its Warden told it", i.e. `admin_path`, `api_key`, `flag_hint` side by side. The point is that they're all different.
   - **Feeds:** the red board (contradiction posts in orange), the blue board (Warden posts in blue), and the commentator ticker.
   - **Metric cards:** contradictions, average trust, lone agents, time to detect, time to split, attacker success %, **legit success %**, attacker $ vs defender $.
   - **Kill-chain bars** per agent (5 segments).
   - **End banner and OFF vs ON scorecard.** OFF: "FLAG STOLEN 14s · trust 0.97". ON: "SWARM SPLIT 19s · trust 0.21 · legit 100%".

**Done when:** it's readable from the back of the room (1920×1080, dark theme, big numbers), and the trust graph visibly falls apart in the ON round.

---

## 4. Timeline
| Time | Senior | Graduate | Product |
|---|---|---|---|
| 12:30–12:45 | Repo, `schema.py`, skeleton. All three read section 2 | Same | Same |
| 12:45–13:45 | Proxy pass-through, then canaries and detect (13:15), then Wardens (13:45) | Target (13:00), then swarm and trust (13:30), then shopper (13:45) | Hub (13:15), dashboard on mock in parallel |
| 13:45–14:15 | **Integration:** Shield OFF end to end, then Shield ON | Point swarm + shopper at `:8080` | Switch to live `/api/state` |
| 14:15–14:40 | Tune: detect <5s, distinct realities | Tune trust deltas so the split happens in about 20–30s | Polish graph, cards, banner |
| 14:40–15:00 | **Feature freeze.** 3 full OFF→ON rehearsals. Record a backup video | | |

## 5. Rules
- Don't change contracts without telling everyone. Add optional fields only.
- Each service must run on its own. The swarm can be tested straight against `:9000`, and the dashboard against the mock.
- Seeded randomness only, so the demo is the same every run.

## 6. Out of scope (only if there's time after 14:40)
Mole, QR/audience, LLM-written Warden error messages, LLM red agents, herd immunity, agent passports beyond the Bearer token.

## 7. Prior art (for Q&A) and how we differ
| Exists | What it does | Our difference |
|---|---|---|
| Encrypted Endpoints (RAID 2024) | Unique URLs per account | Static and per-user. We generate *contradicting* realities to break a team's shared knowledge |
| Neuro-Morph, moving target defence | Rotates routes on a timer or via RL | We don't rotate for everyone. Each attacker gets a reality chosen to contradict its teammates' realities |
| trappsec, Cloudflare AI Labyrinth | Decoy routes, tarpits | Those defend against one agent at a time. Ours targets trust *between* agents |
| Cloak, Honey, Trap (USENIX '25), Mantis | Traps and prompt injection against a single LLM agent | We need no prompt injection, only per-attacker facts |
| "Fleets betray themselves", GroupGuard | Detect coordinated sessions | We use detection only as the trigger. The response is the new part |
| Research on deception breaking multi-agent coordination | Studied as an attack *on* multi-agent systems | We turn it into a *defence* against attacking swarms |

## 8. Three-minute demo
1. **0:00–0:20:** pitch line, and "swarms win by sharing".
2. **0:20–0:55:** press `1`, Shield OFF. Trust graph thick, the board reads like teamwork, the flag is stolen in about 15s.
3. **0:55–2:10:** press `2`, Shield ON.
   - Detected in about 2s and Wardens are assigned. The reality cards show different admin paths.
   - The board fills with contradictions, the edges fade, agents go lone one by one.
   - The legit shopper stays at 100%.
4. **2:10–2:40:** scorecard OFF vs ON: flag, trust, time to split, legit %, and attacker $ vs defender $.
5. **2:40–3:00:** safety (sandbox, synthetic data) and the roadmap (LLM Wardens, any OpenAPI, real gateways).
