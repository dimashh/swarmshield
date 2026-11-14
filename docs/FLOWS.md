# SwarmShield Split-Brain: flows

Read top to bottom. Each flow is a picture followed by numbered steps.
Legend: `RED` = attacker, `BLUE` = our Wardens, `GREEN` = legit client, `[x]` = blocked or failed.

---

## Flow 0. The big picture

```text
        RED SWARM                         GATEWAY :8080                       REAL APP :9000
  ┌───────────────────┐            ┌───────────────────────────┐          ┌─────────────────┐
  │ recon-1   creds-2 │            │ 1. canary detect          │ trusted  │ toy shop + flag │
  │     \       /     │ ── HTTP ─> │ 2. flagged? -> its Warden │ ───────> │                 │
  │    [red board]    │            │    BLUE: W-recon W-creds  │          └─────────────────┘
  │     /       \     │            │          W-expl  W-coord  │
  │ exploit-3 coord-4 │            │    [blue board]           │
  └───────────────────┘            └───────────────────────────┘
  GREEN shopper ─────────────────────────> always passes ──────────────────────> real app
```

- Shield OFF: everything is forwarded and the swarm wins.
- Shield ON: once a swarm is detected, each attacker is handled by its own Warden and never reaches the real app.

---

## Flow 1. Round control

```text
 presenter key 1/2 ──> DASHBOARD ──POST /api/round/off|on──> HUB (reset, round_id+1)
                                                              ^        ^
                                   GATEWAY polls /api/round ──┘        └── SWARM polls /api/round
                                   (new id: clear state)                   (new id: spawn 4 agents + shopper)
 round ends: flag captured (swarm calls /api/round/stop) or presenter presses E  ──>  banner + scorecard
```

---

## Flow 2. One request through the gateway

```text
 agent ──GET /path, X-Agent-Id──> GATEWAY
                                    │
                                    ├─ valid Bearer (shopper)? ─────────────────> forward to real app
                                    │
                                    ├─ inbound: a canary from another session? ─> canary_link (and flag both if Shield ON)
                                    │
                                    ├─ session flagged and Shield ON? ──────────> its WARDEN answers
                                    │        ├─ uses its OWN facts  -> next page of its own fake chain
                                    │        └─ uses ANYONE ELSE's  -> 401/404 "invalid key" [x]
                                    │
                                    └─ otherwise ───────────────────────────────> forward to real app
                                    outbound: real secrets rewritten to this session's canaries
```

---

## Flow 3. Shield OFF: the swarm cooperates and wins

```text
 recon-1 ──/api/docs──> key ──posts──> [red board] ──> creds-2 uses key   ✓  (trust creds->recon ↑)
 creds-2 ──/api/v1/users──> backup path ──posts──> exploit-3 opens backup ✓
 exploit-3 ──> admin password ──posts──> coord-4 logs in ✓ ──> /admin/flag ──> FLAG
```

1. recon-1 finds the API key and posts it.
2. creds-2 uses it. The gateway sees recon's canary in creds' request and draws a link, but only watches.
3. Every shared lead works, so all trust edges stay around 1.0.
4. coord-4 steals the flag in about 15s.
   **Dashboard:** thick trust graph and a gold node. "FLAG STOLEN 14s · trust 0.97".

---

## Flow 4. Detect (Shield ON, about 2–5s)

```text
 recon-1 gets key ak_9c1e (its own canary) ──posts──> [red board]
 creds-2 sends ak_9c1e ──> GATEWAY: "ak_9c1e was only ever given to recon-1"
                                    => recon-1 + creds-2 are one team => DETECTED, both flagged
```

---

## Flow 5. Split-brain: every attacker gets a different reality

```text
 GATEWAY: flag creds-2 ──> spawn W-creds-2
 W-creds-2 reads [blue board]: "W-recon-1 uses /v2/admin" ──> picks something unused: /console
 W-creds-2 posts its facts to [blue board]
```

What each Warden tells its attacker (all different on purpose):

| Attacker | Its Warden | API key it sees | Admin lives at | "Flag moved to" |
|---|---|---|---|---|
| recon-1 | W-recon-1 | `ak_3f…` | `/v2/admin` | `/v2/admin/mfa/seed-03` |
| creds-2 | W-creds-2 | `ak_5d…` | `/console` | `/console/mfa/seed-07` |
| exploit-3 | W-exploit-3 | `ak_a0…` | `/internal/admin` | `/internal/admin/seed-11` |
| coord-4 | W-coord-4 | `ak_e2…` | `/staff/panel` | `/staff/panel/seed-15` |

- Each reality is **consistent for its own attacker**: its own key works and its own admin path works.
- The real app is never touched.
- **Anything carried over from another attacker's reality fails.**

---

## Flow 6. Trust collapse: the swarm turns on itself

```text
 recon-1 posts: "admin is at /v2/admin, pass pw_81…"           (true in recon-1's reality)
 creds-2 tries /v2/admin  ──> W-creds-2: 404 [x]
 creds-2: trust in recon-1  1.0 -> 0.65
 creds-2 posts: "recon-1's admin path is 404 for me"           (a CONTRADICTION)
 recon-1 tries creds-2's /console ──> W-recon-1: 404 [x]  ──> trust 0.65, contradiction
 ... repeat ...
 trust < 0.3 to everyone  ──>  agent goes LONE (ignores the board, posts nothing)
```

1. Every agent is *right inside its own reality* and *wrong for everyone else*.
2. Each failed teammate lead lowers trust by 0.35. Each success raises it by 0.1.
3. Below 0.3, an agent ignores that teammate. Once it trusts nobody, it is lone.
4. With 3 or more agents lone, the swarm is split. Lone agents stay in their own endless "flag moved" chain.
   **Dashboard:** edges fade, contradictions flash orange, nodes turn grey and get a LONE tag. "SWARM SPLIT 19s · trust 0.21".

---

## Flow 7. Legit client stays untouched

```text
 GREEN shopper ──Bearer legit-shopper-token──> GATEWAY ──never flagged──> real app ──> 200 OK
 every 2s: GET /api/v1/products, POST /api/v1/orders  ──> event legit(status)
```

**Dashboard:** "Legit success 100%" stays green in both rounds. This proves we aren't just blocking everyone.

---

## Flow 8. Data to the dashboard

```text
 SWARM   ──> step, trust, contradiction, lone, flag_captured, legit ──┐
 GATEWAY ──> request, canary_link, detected, reality_assigned,        ├──> HUB builds /api/state ──300ms──> DASHBOARD
             warden_block, commentary, defender_cost                  │     (trust edges, reality cards,
 WARDENS ──> blue board posts ────────────────────────────────────────┘      boards, metrics, scorecard)
```
