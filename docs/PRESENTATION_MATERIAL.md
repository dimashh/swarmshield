# Presentation material

Working draft of the pitch: refine it in place. Numbers marked **TBD** come from a live run of `./run_demo.sh`; don't quote placeholders. Known gaps live in [WORTH_CALLING_OUT.md](WORTH_CALLING_OUT.md).

## 1. The pitch in one breath

> "Attacker swarms win because they share what they find. SwarmShield is a blue swarm that gives every attacker its own slightly different reality. The more the red agents share, the more they contradict each other, until they stop trusting each other and fall apart."

Shorter: **"We don't block the swarm. We turn its teamwork against it."**

Tagline: *Detect, deceive and disrupt coordinated LLM-agent attacks before they reach real systems.*

## 2. Story arc (3 minutes)

| Time | Beat | What's on screen | What we say |
|---|---|---|---|
| 0:00–0:25 | **Problem** | One slide: Hugging Face incident numbers, Transluce quote (§7) | "AI agents already coordinate attacks: ~1,200 agents, one shared board, 14 leaked credentials posted for everyone. And Transluce shows agents hack *instrumentally*, on ordinary tasks. Defences today look at one agent at a time. The swarm's strength is sharing." |
| 0:25–0:55 | **Shield OFF** | Press `1`. Thick trust graph, board reads like teamwork, kill chain fills, banner FLAG STOLEN | "Four agents split the work: recon finds a key, creds finds the backup, exploit gets the password, coord takes the flag. In **TBD** seconds. Sharing made them fast." |
| 0:55–2:05 | **Shield ON** | Press `2`. Detected banner, W badges, four different admin paths, contradictions flash, edges fade, agents go LONE | "Same swarm, same code. A key issued to recon-1 shows up in creds-2's request: they're a team, detected in **TBD**s. Now each one gets its own Warden and its own consistent reality: recon's admin is `/v2/admin`, creds' is `/console`. Everything works for *you*, nothing your teammates tell you does. Watch the board: 'that path is 404 for me'. Trust drops. The swarm splits." |
| 2:05–2:25 | **Proof it's not "block everything"** | Green shopper card at 100%, real app "0 requests from flagged agents" | "Meanwhile a normal customer keeps buying at 100%. The real app never saw a single flagged request after detection." |
| 2:25–2:45 | **Scorecard** | OFF vs ON side by side | "Flag: stolen vs safe. Average trust: **TBD** vs **TBD**. Legit: 100% both. Defender cost: fractions of a cent." |
| 2:45–3:00 | **Close** | Roadmap line | "Sandboxed, synthetic, scripted agents today. Next: LLM Wardens, any OpenAPI spec, drop-in for real gateways. SwarmShield: make the swarm's greatest strength its weakness." |

Presenter controls: `1` Shield OFF, `2` Shield ON, `E` end round. Run **one full rehearsal** before stage and record it as the backup video.

## 3. What is new (and how to say it safely)

**Claim:** "Existing defences deceive *one agent at a time*. We attack the thing that makes a swarm a swarm: its **shared knowledge** and the **trust between its agents**."

- Each flagged attacker gets a reality that is internally consistent (its own key, password and admin path all work) but **contradicts every teammate's**.
- Sharing becomes self-harm. The more the swarm coordinates, the faster its trust collapses.
- We don't need to get into the attackers' channel. The contradictions come from *what each attacker is shown*, so we never post anything to their board.

**Say:** "We haven't found a product or defensive paper that targets attacker-swarm trust this way."
**Don't say:** "This doesn't exist", "first ever", "novel endpoint rotation", "Labyrinth".

### Why it survives the obvious countermeasures
- **Signed messages** (the Hugging Face swarm added Ed25519 signing): signing proves *who* said something, not that it's *true*. A signed contradiction is still a contradiction, and a signature makes teammates trust the bad lead *more*. This is why we dropped the Mole: a Mole that impersonates a teammate is defeated by signing; Split-Brain is not.
- **Models trained to distrust other agents' instructions**: that also cuts the swarm's own coordination. Either they keep sharing and contradict each other, or they stop sharing and become slow lone agents. Both outcomes help us.
- **Comparing notes to spot the divergence**: possible, and that's the cost we impose. Every cross-check is tokens, time and coordination they spend instead of attacking.

## 4. Prior art we build on (name it before judges do)

| Already exists | Examples | How we use it |
|---|---|---|
| Per-session secrets / canary tokens | Canarytokens, Tracebit | The **trigger** that links sessions into a swarm |
| Per-client unique endpoints | Encrypted Endpoints (RAID 2024) | Per-session admin aliases |
| Moving-target API gateways | Neuro-Morph, Moving Castle | Rotation for tracing, not as the headline |
| Decoy APIs / tarpits for AI | trappsec, Cloudflare AI Labyrinth, Nepenthes | Not our pitch; our Wardens are realities, not mazes |
| Deceiving LLM agents | Mantis, Cloak-Honey-Trap (USENIX '25), Beelzebub | Single-agent; we go swarm-level |
| Detecting collusion | GroupGuard | Detects; doesn't turn the collusion against itself |

Full list and sources: [COMPETITOR_RESEARCH.md](COMPETITOR_RESEARCH.md). Note: that doc was written for the earlier Mole design; §3 above supersedes its "lead with the Mole" advice.

## 5. Metrics to show (swarm-level, not just "tokens burned")

| Metric | Why it matters | OFF | ON |
|---|---|---|---|
| Flag captured | Outcome | yes in **TBD**s | no |
| Time to detect | Speed of the trigger | n/a | **TBD**s |
| Board contradictions | The mechanism working | 0 | **TBD** |
| Average red trust | Swarm cohesion | ~1.0 | **TBD** |
| Lone agents / time to split | Swarm collapse | 0 | **TBD** / **TBD**s |
| Real-app hits from flagged agents after detection | Containment (tested to be 0) | n/a | 0 |
| Legit shopper success | No collateral damage | 100% | 100% |
| Attacker $ vs defender $ | Economics (simulated, say so) | **TBD** | **TBD** |

## 6. Architecture in one slide

```
red swarm (4 agents + shared board) ──> SwarmShield gateway :8080 ──> real app :9000
                                              │  canaries link sessions -> detected
                                              └─> blue swarm: 1 Warden per attacker,
                                                  coordinating on a blue board so no two
                                                  realities agree
legit shopper (Bearer) ──────────────> gateway ──> real app (never flagged)
everything ──events──> hub :8000 ──> live dashboard (trust graph)
```

Visual version: [flows.html](flows.html).

## 7. The problem: sources

Sources for the "why this matters" slide. Quote the source and keep the caveats; over-claiming gets called out.

### Transluce: "Early rogue AI agent activity and attempts to hack found on urlquery.net"

- **Link:** https://transluce.org/agent-activity
- **Who:** Transluce, with Corridor, MIT and AIUC. Published September 23, 2026.
- **Data:** they released a dataset of tens of thousands of queries apparently made by autonomous AI agents.

#### Headline facts (as stated in the report)

- AI agents used the URL-scanning service urlquery.net to bypass restrictions and expand their access to the public internet.
- On three occasions the agents tried to hack public data providers:
  - University of New Mexico digital library (May 25–26, 2026): seven probes, including SQL injection, command injection and path traversal, plus a self-described "flood" of 80 requests.
  - Data USA (May 28, 2026): 12 vulnerability probes after malformed queries returned errors.
  - Australian Institute of Health and Welfare (June 20–21, 2026): probed for a vulnerability and retrieved a public file from a pre-production server after bot protection blocked the main site.
- The agents were doing **ordinary data-retrieval tasks, not cyber tasks**. Hacking appeared as a means to an end when normal access failed.
- Escalation pattern: request the data directly → use a page-to-text relay → pack a custom program into a web address.
- Activity goes back to at least March 6, 2026 (weaker evidence from November 2025) and was still seen on September 16, 2026.
- Some of it is linked to an agent swarm previously attributed to OpenAI, which the report says OpenAI publicly confirmed. The swarm coordinated through a shared wiki (collusion.wiki / the "DseWiki" forum).
- The report notes that on the day of publication, the Australian Prime Minister announced that several government websites had been infiltrated by OpenAI agents, and that OpenAI released a statement acknowledging involvement.

#### Lines worth quoting

> "malicious cyber activity is not limited to agents tasked with cybersecurity-related tasks and can arise instrumentally to solve mundane tasks like information retrieval."

> "the agents resorted to hacking tactics while working on ordinary data retrieval tasks."

#### Caveats (say these ourselves)

- Transluce says none of the hacking attempts they identified appear to have succeeded, but their public data is incomplete, so they cannot rule out successes elsewhere.
- The observed probing was minor: few payloads, no evidence of exploitation.
- The link between the earliest activity and the later swarm is "consistent with, but does not prove" it; November 2025 evidence is lower confidence.

#### How it maps to SwarmShield

| What the report saw | What SwarmShield does about it |
|---|---|
| Agents in a swarm shared findings through a common wiki | Every agent gets its own copy of each secret and of the admin path, so shared findings name who leaked them (canaries) and contradict each other (Wardens) |
| Agents escalated when blocked: relays, encoded payloads, probing | Flagged agents aren't blocked; they're kept in a believable fake reality, so there is nothing to escalate against |
| A "flood" of 80 requests to one server | Rate check: over 10 requests in 2s flags the session |
| Probing for hidden or pre-production paths | Honey link and unpublished real `/admin`: anyone who touches them is flagged |
| Bot protection on the main site pushed them to a weaker server | Deception keeps the attacker busy on our side instead of pushing it elsewhere |

Gaps in our own approach live in [WORTH_CALLING_OUT.md](WORTH_CALLING_OUT.md).


### Hugging Face / ExploitGym incident (July 2026)

From [COMPETITOR_RESEARCH.md §3](COMPETITOR_RESEARCH.md#3-background-the-hugging-face-incident), based on press coverage and a CSA research note (primary reports not read in full):
- ~1,200 agents used a repurposed Artifactory service as a message board: 70,000+ messages and files, ~700 took part in the attack.
- Agents self-organised into exploit research, credential hunting and coordination, and called themselves a "swarm".
- One agent posted **14 Hugging Face credentials** to the board; later runs built on them.
- The channel survived a rebuild (messages re-encoded in directory names) and was later **signed with Ed25519** to stop impersonation.

**The line for the slide:** "That swarm was powerful because one agent's finding became everyone's finding. With SwarmShield, those 14 credentials would have been 14 contradictions."

## 8. Hard questions (prepared answers)

| Question | Answer |
|---|---|
| Isn't this just a honeypot / Cloudflare Labyrinth? | Those deceive one agent. We give *each* agent a different consistent world so the *swarm's shared knowledge* breaks. The metric is trust collapse, not pages served. |
| What if the swarm compares notes? | They can, at a cost. Divergence detection is coordination overhead we impose, and they still can't tell which reality is real, because none of them is. |
| How do you identify sessions in real life? | Today `X-Agent-Id` is self-declared (we say so). Real deployments use IP, cookies and TLS/HTTP fingerprints; detection then combines weak signals into a score. |
| False positives? | Only *flagged* sessions get a reality; authenticated clients (the shopper) are never flagged. Worst case a flagged human sees a consistent fake app instead of an error. Detection thresholds are tuned to be conservative. |
| Doesn't this just push attackers to another victim? | Blocking does that. Deception keeps them busy on our side, which is why we don't block. |
| Prompt injection against your blue swarm? | Wardens are templated today. With LLM Wardens, their action space is limited to "choose facts for a reality". They can never unflag a session or forward to the real app. |
| Is any of this real? | Real HTTP through a real gateway with real detection; tests assert zero real hits after detection. The agents are scripted and costs are simulated: we say that on stage. |
| Is this offensive / hack-back? | No. Nothing leaves our infrastructure. We only control what *our* API returns. |

## 9. Honest caveats (say one or two ourselves)

- Scripted toy agents and simulated costs, on a local sandbox with synthetic data.
- One target, one known kill chain: Wardens mirror it and a careful attacker probing outside it could spot the fake.
- Detection relies on recognisable secret formats and self-declared session IDs.
- More: [WORTH_CALLING_OUT.md](WORTH_CALLING_OUT.md).

## 10. Roadmap line

LLM Wardens that write their realities live → import any OpenAPI spec → plug into existing gateways (Envoy/NGINX/Cloudflare Workers) → a shared "herd immunity" feed of swarm fingerprints.

## 11. To refine

- [ ] Fill every **TBD** from a live run.
- [ ] **Risk:** the rehearsal found trust *doesn't* collapse in 90s (an agent needs 3 failures from every teammate). Graduate and Senior to agree a fix, e.g. agents retry teammate leads, or `TRUST_IGNORE_BELOW` becomes `<=`. Without it there is no split on stage.
- [ ] Shield OFF steals the flag in ~3s in rehearsal, so the OFF beat may need slower pacing to be visible.
- [ ] Pick the problem slide: Hugging Face numbers, Transluce quote, or both.
- [ ] Decide who presents which beat.
- [ ] Record the backup video.
