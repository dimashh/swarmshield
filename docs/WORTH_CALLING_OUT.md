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
- **Wardens are scripted, not agents.** "Blue swarm" coordination is a shared board so two Wardens never give out the same admin path. They don't reason or adapt.
- **Defender cost is simulated.** `defender_cost` is a fixed price per fake page, not a measured cost.

## Scope of the demo

- **Synthetic, local sandbox only.** Fixed secrets and a fake flag on localhost. Nothing touches real systems.
- **One target, one known kill chain.** The red swarm and target are written by us, so detection and deception are tuned to an attacker we fully understand.
- **Single gateway process, state in memory.** No persistence, no horizontal scaling; a restart forgets every canary and flag.
- **Response rewriting adds latency and needs JSON.** Fine for a demo; in production it is a WAF/reverse-proxy feature with real performance cost.
- **The hub is trusted and unauthenticated.** Anyone on localhost could post events or read the blue board.

## What is solid

- Canaries are unique per session, per round, per window, so a reused value names both the leaker and the reuser.
- After detection, flagged sessions never reach the real target; tests assert zero real hits.
- The shopper is never rewritten or flagged, also tested.
- Tests run the gateway against the Graduate's real target: Shield OFF reaches the flag, Shield ON never does.
