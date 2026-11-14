# Presentation material: the problem

Sources for the "why this matters" slides. Quote the source and keep the caveats; over-claiming gets called out.

## Transluce: "Early rogue AI agent activity and attempts to hack found on urlquery.net"

- **Link:** https://transluce.org/agent-activity
- **Who:** Transluce, with Corridor, MIT and AIUC. Published September 23, 2026.
- **Data:** they released a dataset of tens of thousands of queries apparently made by autonomous AI agents.

### Headline facts (as stated in the report)

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

### Lines worth quoting

> "malicious cyber activity is not limited to agents tasked with cybersecurity-related tasks and can arise instrumentally to solve mundane tasks like information retrieval."

> "the agents resorted to hacking tactics while working on ordinary data retrieval tasks."

### Caveats (say these ourselves)

- Transluce says none of the hacking attempts they identified appear to have succeeded, but their public data is incomplete, so they cannot rule out successes elsewhere.
- The observed probing was minor: few payloads, no evidence of exploitation.
- The link between the earliest activity and the later swarm is "consistent with, but does not prove" it; November 2025 evidence is lower confidence.

### How it maps to SwarmShield

| What the report saw | What SwarmShield does about it |
|---|---|
| Agents in a swarm shared findings through a common wiki | Every agent gets its own copy of each secret and of the admin path, so shared findings name who leaked them (canaries) and contradict each other (Wardens) |
| Agents escalated when blocked: relays, encoded payloads, probing | Flagged agents aren't blocked; they're kept in a believable fake reality, so there is nothing to escalate against |
| A "flood" of 80 requests to one server | Rate check: over 10 requests in 2s flags the session |
| Probing for hidden or pre-production paths | Honey link and unpublished real `/admin`: anyone who touches them is flagged |
| Bot protection on the main site pushed them to a weaker server | Deception keeps the attacker busy on our side instead of pushing it elsewhere |

Gaps in our own approach live in [WORTH_CALLING_OUT.md](WORTH_CALLING_OUT.md).
