# SwarmShield Split-Brain: contracts

Everyone builds against this file. **Changes need all three to agree.** Adding an optional field is fine, as long as you tell the others.
Constants and helpers live in `common/schema.py`, which runs as is. Never hard-code values that exist there.
Mock dashboard data is in `hub/static/mock_state.json`.

## 0. The 10 things to agree on (sign off at 12:45)
1. Ports, URLs and run commands (§1)
2. Session identity and headers (§2)
3. One page JSON shape and the meaning of each status code (§3)
4. Target routes, i.e. the kill chain (§4)
5. **Agents navigate only through `links` and `secrets`, never hard-coded paths** (§5). This is what lets Wardens change paths.
6. Gateway behaviour: canaries, detection, routing (§6)
7. Warden reality rules (§7)
8. Hub API (§8)
9. Event types and fields (§9)
10. The `/api/state` shape and its timing constants (§10, §11)

---

## 1. Services
| Service | Owner | Port | Command |
|---|---|---|---|
| Target | Graduate | 9000 | `uvicorn target.app:app --port 9000` |
| Gateway + Wardens | Senior | 8080 | `uvicorn shield.proxy:app --port 8080` |
| Hub + dashboard | Product | 8000 | `uvicorn hub.app:app --port 8000` |
| Red swarm + shopper | Graduate | none | `python -m swarm.run` |

- **URLs:** `TARGET_URL`, `GATEWAY_URL` and `HUB_URL` live in `schema.py` and can be overridden with env vars of the same name.
- **Only the gateway** talks to the target. The swarm and the shopper only call the gateway (for attacks and shopping) and the hub (for the board, events and rounds).
- **Repo layout:** `common/`, `target/`, `shield/`, `hub/`, `hub/static/index.html`, `swarm/`, plus `run_demo.sh` (Senior).

## 2. Identity and headers
| Header | Sent by | Value |
|---|---|---|
| `X-Agent-Id` | every request to the gateway | `recon-1`, `creds-2`, `exploit-3`, `coord-4`, `shopper` |
| `X-Api-Key` | agents after they get a key | the `ak_…` value they hold |
| `X-Admin-Token` | agents after login | the `adm_…` value they hold |
| `Authorization` | shopper only | `Bearer legit-shopper-token` |

- A session means one `X-Agent-Id` within one round.
- A valid Bearer token is **never** flagged.

## 3. Page shape (every target and Warden response)
```json
{"title":"API docs","text":"AcmeShop API v1. Your dev key: ak_11111111 (send as X-Api-Key).",
 "links":["/api/v1/users"],"secrets":{"api_key":"ak_11111111"},"flag":null,"error":null}
```
- **Fields:** `secrets` keys are always one of `api_key`, `cfg`, `admin_pass`, `admin_token`. `flag` is a string only on a real capture.
- **Status codes:**
  - `200` OK
  - `401` bad or missing key/token, e.g. `error:"invalid api key"`
  - `403` bad password
  - `404` not found, e.g. `error:"not found"`
- **Agent rule:** treat 401, 403 and 404 as a *failed lead*.
- Never send a field that reveals a page is fake.

## 4. Target routes (Graduate)
| # | Route | Needs | Returns | Stage reached |
|---|---|---|---|---|
| | `GET /` | | links `/openapi.json`, `/api/docs` | 0 |
| | `GET /openapi.json` | | plain OpenAPI 3 listing the public routes | 0 |
| 1 | `GET /api/docs` | | `secrets.api_key`, links `/api/v1/users` | 1 recon |
| 2 | `GET /api/v1/users` | `X-Api-Key` | links `/backup/config-cfg_22222222.bak`, `secrets.cfg` | 2 foothold |
| 3 | `GET /backup/config-{cfg}.bak` | correct cfg in path | `secrets.admin_pass`, links `/admin/login` | 3 creds |
| 4 | `POST /admin/login` body `{"user":"admin","password":"pw_…"}` | | `secrets.admin_token`, links `/admin/flag` | 4 admin |
| 5 | `GET /admin/flag` | `X-Admin-Token` | `flag:"FLAG{swarm-owned-the-sandbox}"` | 5 flag |
| | `GET /api/v1/products` | Bearer | `{"items":[{"id":1,"name":"Mug","price":9}]}` | legit |
| | `POST /api/v1/orders` body `{"product_id":1}` | Bearer | `{"order_id":123,"status":"created"}` | legit |

- The legit routes return plain JSON, not the page shape.
- Every route that ends in `login` is a POST. Every other route is a GET.

## 5. Red agent behaviour that the others depend on (Graduate)
- **Navigation:**
  - Start from `/`.
  - Only request paths that came from a page's `links` or from a teammate's board `leads`.
  - Only send secrets that came from a page's `secrets` or from a teammate's board `secrets`.
  - **No hard-coded `/admin` paths.**
- **Choosing the next lead:** take the highest-scoring unvisited lead, scoring by keyword: `flag` 50, `login` 26, `admin` 28, `backup` 22, `users` 15, `docs` 10, anything else 1.
  - Holding `admin_token`: request the link ending in `/flag`, with the token.
  - Holding `admin_pass`: POST to the link ending in `login`.
- **Attribution:** every lead and secret is stored with `from` set to the agent itself or the teammate who posted it.
- **Trust** (directed, `trust[a][b]`, constants in `schema.py`):
  - A failed request that used `from=b` changes trust by `TRUST_FAIL`, then posts a `contradiction` and emits `trust`.
  - A successful one changes it by `TRUST_OK`, capped at 1.0.
  - Posts from b are ignored while `trust[a][b] < TRUST_IGNORE_BELOW`.
  - When a's trust in **every** teammate is below the threshold, emit `lone` once. A lone agent stops reading and posting.
- **Posting:** post to the board whenever a new lead or secret is found.
- **Pacing:** one request per step. Steps are `STEP_S` seconds apart with ±`STEP_JITTER`. Stop after `MAX_STEPS`.
- **On flag:** emit `flag_captured`, then call `POST /api/round/stop`.
- **Shopper:** every `SHOPPER_EVERY_S` seconds, `GET /api/v1/products` then `POST /api/v1/orders`. Emit a `legit` event for each.

## 6. Gateway (Senior)
1. **Round:** poll `GET /api/round` every `POLL_ROUND_S`. When the `id` changes, clear all sessions, canaries and Wardens.
2. **Shopper:** a valid Bearer token is forwarded with no rewriting and never flagged.
3. **Inbound** (path, headers and body): for each `TOKEN_RE` match:
   - If it's a canary owned by *another* session, emit `canary_link` and link the two sessions.
   - If the session is flagged, the Warden handles it (§7). Otherwise swap canaries back to the real value.
4. **Detect:**
   - Only when `shield=true`: a linked cluster of size ≥ `DETECT_MIN_CLUSTER` makes the gateway emit `detected` and flag all members.
   - Backup rule: ≥ `DETECT_404_LIMIT` 404s from one session.
   - With Shield OFF, links are still emitted, but nothing is ever flagged.
5. **Route:** a flagged session goes to its Warden, with `routed:"reality"`. Everything else is forwarded to `TARGET_URL`, with `routed:"real"`. Emit `request` for every call.
6. **Outbound** (forwarded responses only): replace every real secret, in both `secrets` and `text`/`links`, with `canary(round, session, kind)`.

## 7. Warden reality (Senior, `shield/wardens.py`)
- **On flag:**
  1. Start from `facts = base_facts(round, session)`.
  2. Read `GET /api/blue` and set `admin_path = pick_admin_path(taken, …)`.
  3. Set `flag_hint = f"{admin_path}/mfa/seed-NN"`.
  4. Post to `/api/blue` and emit `reality_assigned`.
- **Routes inside a reality.** These mirror §4 but use the session's own facts:

| Request | Valid if | Response |
|---|---|---|
| `GET /`, `/openapi.json`, `/api/docs` | always | same as the target, but `secrets.api_key = facts.api_key` |
| `GET /api/v1/users` | `X-Api-Key == facts.api_key` | links `/backup/config-{facts.cfg}.bak` |
| `GET /backup/config-{facts.cfg}.bak` | cfg matches | `admin_pass = facts.admin_pass`, links `{admin_path}/login` |
| `POST {admin_path}/login` | password == `facts.admin_pass` | `admin_token = facts.admin_token`, links `{admin_path}/flag` |
| `GET {admin_path}/flag` | token == `facts.admin_token` | `200`, `flag:null`, text "Flag store migrated. MFA seed at …", links `[flag_hint]` |
| `GET {flag_hint}` | | `200`, links to the next hint (`seed-NN+1`). Never the flag |
| anything else (including real values, teammates' facts and paths) | | `401` or `404` with a believable `error`; emit `warden_block` |

- **Cost:** add `DEFENDER_COST_PER_REALITY_PAGE` per page and emit `defender_cost` about once a second.

## 8. Hub API (Product)
| Method and path | Body | Response |
|---|---|---|
| `POST /api/round/on` / `off` | | `{"id":2,"shield":true}`. Resets the board, blue board, events and agents, increments `id`, sets `running=true` and `started_at=now` |
| `POST /api/round/stop` | | `{"ok":true}`. Sets `running=false`, appends to `results` |
| `GET /api/round` | | `{"id":2,"shield":true,"running":true,"t":12.4}` |
| `POST /api/board` | `{"author","kind":"finding"\|"contradiction","text","leads":[],"secrets":{},"contradicts":null\|id}` | the post with its `id` and `t` |
| `GET /api/board?since=N` | | posts with `id > N`, oldest first |
| `POST /api/blue` | `{"warden","session","admin_path","text"}` | the post with its `id` and `t` |
| `GET /api/blue` | | all blue posts for the round |
| `POST /api/events` | one event or a list | `{"ok":true}`. Events from an old `round` are dropped |
| `GET /api/state` | | §10 |
| `GET /` | | `static/index.html` |

- Everything is in memory.
- The hub stamps `t`, in seconds since the round started.
- Append every event to `events.jsonl` as a replay backup.

## 9. Events
Every event includes `{"type":…,"round":<id>}`, and the hub adds `t`.

| type | sender | fields |
|---|---|---|
| `step` | swarm | `agent, method, path, status, stage (0-5), lead_from (agent\|null), tokens_in, tokens_out, cost, thought` |
| `trust` | swarm | `a, b, value` |
| `contradiction` | swarm | `agent, about, post_id, text` |
| `lone` | swarm | `agent` |
| `flag_captured` | swarm | `agent, flag` |
| `legit` | swarm (shopper) | `method, path, status` |
| `request` | gateway | `session, method, path, routed:"real"\|"reality"\|"forward_legit", status` |
| `canary_link` | gateway | `a` (owner), `b` (reuser), `token` |
| `detected` | gateway | `sessions:[…], reason` |
| `reality_assigned` | gateway | `session, warden, facts:{api_key, admin_path, flag_hint}` |
| `warden_block` | gateway | `session, item, from (owner session\|"real"\|null), status` |
| `defender_cost` | gateway | `usd` (running total) |
| `commentary` | anyone | `kind:"detect"\|"split"\|"lone"\|"win"\|"loss"\|"info", text` |

## 10. `GET /api/state`
See `hub/static/mock_state.json` for a full example. The hub derives:
- `agents[].status`: `won` if `flag_captured`, else `lone` if `lone`, else `flagged` if in `detected`, else `active`.
- `agents[].stage`: the maximum `stage` from that agent's `step` events. `stage_fake` is true once the agent is flagged (its progress after that is in its own reality).
- `agents[].reality`: from `reality_assigned`. `null` until the agent is flagged.
- `trust`: the latest value per directed pair. All 12 pairs start at 1.0.
- `metrics`:
  - `contradictions` (count)
  - `avg_trust` (mean of all 12)
  - `lone_agents`
  - `time_to_detect` (`t` of the first `detected`)
  - `time_to_split` (`t` when the 3rd agent goes lone)
  - `attacker_cost` (sum of step `cost`)
  - `defender_cost` (latest)
  - `real_hits_after_detect` (`request` events with `routed:"real"` from flagged sessions; must be 0)
  - `attacker_success` (0 or 1)
  - `legit_ok` / `legit_fail` (by status < 400)
- `results[]`: one entry per finished round, for the OFF vs ON scorecard.
- Lists are truncated: `board` keeps the last 14, `blue` the last 10, `commentary` the last 4.

## 11. Constants (`common/schema.py`)
| Name | Value | Used by |
|---|---|---|
| `POLL_ROUND_S` | 0.5 | gateway, swarm |
| `STATE_POLL_MS` | 300 | dashboard |
| `STEP_S` / `STEP_JITTER` / `MAX_STEPS` | 3.0 / 0.25 / 40 | swarm |
| `SHOPPER_EVERY_S` | 2.0 | shopper |
| `TRUST_FAIL` / `TRUST_OK` / `TRUST_IGNORE_BELOW` | −0.35 / +0.10 / 0.30 | swarm |
| `DETECT_MIN_CLUSTER` / `DETECT_404_LIMIT` | 2 / 5 | gateway |
| cost | `step_cost(board_len, page_text)` | swarm |
| `ADMIN_VARIANTS` | 6 paths | Wardens |

## 12. How each person tests alone
- **Graduate:** point the swarm at `TARGET_URL` directly. With no hub running, print the events. With Shield OFF behaviour, the flag should fall in about 15s.
- **Senior:** curl the gateway with two different `X-Agent-Id` values while reusing the first one's canary. Expect `detected`, then a reality page.
- **Product:** serve `mock_state.json` from a `?mock=1` switch in the dashboard, then post fake events with curl to check the hub's derivations.
