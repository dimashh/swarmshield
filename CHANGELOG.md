# Changelog

One line per commit, newest first. Everyone commits to `main`: run `git pull --rebase origin main` before you start and before every push.

- 2026-11-14 `shield`: fix double Warden assignment under concurrent requests; integration findings (detect 7.8s, no split yet) in WORTH_CALLING_OUT (Senior)
- 2026-11-14 `shield`: detection is now the named **Sentinel** (`shield/detect.py` -> `shield/sentinel.py`); every alert is posted to the blue board as `warden:"Sentinel"` (`admin_path:null`) before the Wardens post, plus `Sentinel:` commentary (Senior)
- 2026-11-14 `docs`: `docs/PRESENTATION_MATERIAL.md` §0 goals and angles: swarm vs swarm as the core angle, red vs blue agent table, Sentinel added to the blue swarm (to-refine task for Senior), deploy-ready gateway goal (Devin)
- 2026-11-14 `docs`: `docs/PRESENTATION_MATERIAL.md` pitch draft: one-liner, 3-min script, novelty claim, countermeasures, prior art, metrics, Q&A, caveats, to-refine list (Devin)
- 2026-11-14 `docs`: `docs/PRESENTATION_MATERIAL.md`, problem-statement sources for the slides (Transluce agent-activity report: facts, quotes, caveats, mapping to SwarmShield) (Senior)
- 2026-11-14 `shield`: `run_demo.sh` (hub, target, gateway, swarm; stand-in `shield/stubhub.py` until `hub/app.py` lands; logs in `logs/`), `python -m shield.rehearse` scripted swarm reports detect time/real hits/shopper/trust for OFF and ON (Senior)
- 2026-11-14 `shield`: per-session `/admin-xxxx` aliases, canaries and aliases rotate every `ROTATE_S` (owner's old copies still work), Shield ON adds a honey link to pages and flags honey visits, direct `/admin` use and > `RATE_LIMIT` req/`RATE_WINDOW_S`; `docs/WORTH_CALLING_OUT.md`; gateway+real-target integration tests (Senior)
- 2026-11-14 `target`: AcmeShop toy target `target/app.py` on :9000 (kill chain `/` -> `/api/docs` -> `/api/v1/users` -> backup cfg -> `POST /admin/login` -> `/admin/flag`, shopper products/orders; all errors 401/403/404 in `page()` shape) (Graduate)
- 2026-11-14 `shield`: Wardens give each flagged session its own reality (own key/cfg/pass/token, unique `admin_path` via blue board, endless `/mfa/seed-NN` chain, never the flag); cross-reality or real values get 401/403/404 + `warden_block`; emits `reality_assigned`, `defender_cost` (Senior)
- 2026-11-14 `shield`: canaries (outbound rewrite incl. paths, inbound swap-back), `canary_link`, detection (cluster >= 2 or 5x 404, Shield ON only), flagged sessions routed to a Warden stub (404) and never reach the target (Senior)
- 2026-11-14 `shield`: pass-through gateway `shield/proxy.py` (forwards to target, emits `request`, shopper `forward_legit`, polls `/api/round`); `emit` logs hub-down once instead of every batch (Senior)
- 2026-11-14 `common`: URLs can be set by env var, `flag_hint`/`next_hint` give decimal `seed-NN`, new `common/hub.py` client (`get_round`, board/blue helpers, non-blocking `emit`), `tests/` + `requirements-dev.txt` (Senior)
