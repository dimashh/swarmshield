# Worth calling out

Known gaps and simplifications. Say these before someone else does. Each line: what we did, what a real deployment would need.

## Detection

- **Sessions are self-declared.** Agents send `X-Agent-Id`, and we trust it. Real traffic needs session identity from IP, cookies, TLS/HTTP fingerprints, and an attacker can rotate all of those.
- **Canary reuse proves coordination only if copies travel.** A swarm that shares *conclusions* ("admin is behind a login") but never pastes raw values is not linked by canaries. The honey link, the unpublished `/admin` rule and the rate check are the backup layers.
- **Value-level canaries need recognisable secrets.** We detect `ak_/cfg_/pw_/adm_` + 8 hex because we control the format. Real secrets (JWTs, cookies, free-text passwords) need per-format rewriting or a token service.
- **The rate check won't fire in the demo.** Our swarm is paced at about 1 request per 3s per agent to look human-ish; the check is aimed at scripted scanners. An LLM agent that paces itself evades it.
- **The 404 rule can flag real users** who mistype URLs. It is a backup with a high threshold, never the main signal.
- **No scoring or ML.** Each signal is a hard rule. A real system would combine weak signals into a score and tune thresholds on real traffic to control false positives.
- **The shopper is exempt by token.** A valid Bearer token is never flagged. A stolen shopper token would bypass the shield; real systems still score authenticated sessions.

## Deception (canaries, rotation, honey links, Wardens)

- **Rotation is for tracing, not expiry.** Copies rotate every `ROTATE_S`, but a session's old copies keep working so the agent never sees random breakage. Real key rotation also expires old values.
- **Endpoint rotation covers `/admin` only.** The other routes (`/api/docs`, `/api/v1/users`, `/backup/...`) keep their real names; the backup path is personalised only through the `cfg` canary inside it.
- **Honey links are only on page-shaped JSON.** HTML, OpenAPI documents and other formats are not baited.
- **A Warden is only as convincing as its route table.** It mirrors one known kill chain. An attacker that probes routes outside it, compares timing or response headers against the real app, or reads the real OpenAPI before being flagged can spot the fake.
- **Endless MFA hints are a tell.** Seed-NN → NN+1 forever is cheap for us, but a careful attacker notices the loop. Good enough to burn tokens and time, not to fool a human for long.
- **Sentinel is a rule set, not an agent.** It applies fixed rules (canary reuse, honey link, unpublished path, rate, 404s) and posts its alerts to the blue board; it doesn't learn or reason.
- **Wardens are scripted, not agents.** "Blue swarm" coordination is a shared board so two Wardens never give out the same admin path. They don't reason or adapt.
- **Defender cost is simulated.** `defender_cost` is a fixed price per fake page, not a measured cost.

## Rehearsal findings (`python -m shield.rehearse`, our simplified swarm)

- **Shield OFF is fast:** the sharing swarm took the flag in 3.3s (6 requests), not ~15s. Sharing parallelises the kill chain.
- **Trust collapse did not happen in 90s.** Agents never retry a visited lead, so each teammate causes about one contradiction. With `TRUST_FAIL` −0.35 and `TRUST_IGNORE_BELOW` 0.30, an agent needs 3 failures from *each* teammate to go lone (1.0 − 2×0.35 = 0.30 is not below 0.30). Whether the real swarm splits depends on its retry logic.

## Integration findings (hub PR #3 + swarm PR #4 + gateway + real shop, 2026-11-14)

- **Shield OFF works:** flag at 15.5s, as planned.
- **Shield ON (swarm PR #4 at f276fac): detect 7.6s (target < 5s), 0 real hits after detection, 27 contradictions, all 4 agents lone, split at 35.8s (target 20-30s).** An earlier swarm build only reached 1/4 lone: a lone agent stops posting, so teammates kept trusting it. Fixed swarm-side by going lone once every teammate it relied on is distrusted.
- **Shopper runs (swarm `swarm/legit.py`):** 30/30 legit requests OK through the gateway in a 30s Shield ON run (all `forward_legit`, never flagged). `legit_pct` is now backed by real traffic.
- **Fixed:** two parallel requests from one newly flagged agent could build two Wardens for it (seen live for coord-4). Warden assignment is now serialised.

## Red swarm (`swarm/run.py`, Graduate)

- **The swarm is scripted, not an LLM.** Keyword scores pick the next lead and `tokens_in/out` and `cost` are simulated by `step_cost`. A real LLM swarm would reason about contradictions instead of applying fixed trust deltas.
- **Agents trust teammates first.** They try the newest teammate secret before their own, which is what makes canaries travel. A swarm that prefers its own values would be linked later or only by the honey/`/admin`/404 rules.
- **Lone means "burned by everyone I relied on", not by all three teammates.** Followers that only reuse others' finds never post a failing tip, so under the original rule nobody went lone. Now an agent goes lone once every teammate whose leads or secrets it acted on is below 0.30 (6 Shield ON runs with the stand-in hub: 3+ lone in 3 of them, 3rd lone at 13.2s, 22.4s and 35.8s; the other 3 had only 0-1 lone after 30-40s, because a teammate whose secrets already failed rarely posts enough new ones to fail 3 times). It never counts teammates it hasn't tried.
- **No second-hand distrust.** An agent lowers trust only from its own failed requests, never from a teammate's `contradiction` post. Gossip would make the split faster but is not in the contract.
- **Agents don't revisit pages.** After `ROTATE_S` they keep using the copies they already have (still valid for them), so rotation shows up only through newly visited pages.
- **Detection time depends on the swarm's order.** The first canary replay happens when the second agent uses the first one's key (about 6-10s), above the plan's < 5s.

## Scope of the demo

- **Synthetic, local sandbox only.** Fixed secrets and a fake flag on localhost. Nothing touches real systems.
- **One target, one known kill chain.** The red swarm and target are written by us, so detection and deception are tuned to an attacker we fully understand.
- **Single gateway process, state in memory.** No persistence, no horizontal scaling; a restart forgets every canary and flag.
- **Response rewriting adds latency and needs JSON.** Fine for a demo; in production it is a WAF/reverse-proxy feature with real performance cost.
- **The hub is trusted and unauthenticated.** Anyone on localhost could post events or read the blue board.

## Dashboard and hub

- **The trust graph is red's own state.** Agents report their trust scores to the hub; a real defender cannot see inside the attacker, only infer the split from requests stopping and diverging.
- **Dollar figures on the dashboard are scaled ×10,000** so they read in thousands. The underlying per-step costs are toy numbers from `step_cost`; say "illustrative" on stage.
- **The API view is drawn from gateway `request` events** (last 60). Each attacker's dot sits on the tile of its latest request; routes outside the known set are drawn on Home / API docs.
- **Step mode is driven by the dashboard tab.** It posts the stage pauses itself; with two dashboards open in step mode, both pause the round. Requests already in flight finish, so a stage can move on by one step before the freeze.
- **Pause freezes the swarm, shopper and round clock, not the gateway.** Key/alias rotation (`ROTATE_S`) keeps ticking during a pause; old copies still work for their owner, so nothing breaks.
- **The dashboard's story phases are inferred** from detections, realities and lone agents; a round that never detects stays on step 1.
- **The hub keeps everything in memory.** Restarting it loses the round; only `events.jsonl` survives for replay.
- **`fake_round` is a scripted replay for rehearsal,** not the real swarm; numbers on stage come from the live services.

## What is solid

- Canaries are unique per session, per round, per window, so a reused value names both the leaker and the reuser.
- After detection, flagged sessions never reach the real target; tests assert zero real hits.
- The shopper is never rewritten or flagged, also tested.
- Tests run the gateway against the Graduate's real target: Shield OFF reaches the flag, Shield ON never does.
