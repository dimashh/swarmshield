"""Shield rehearsal: a scripted 4-agent swarm (CONTRACTS §5, simplified) plus the shopper, through the gateway.
Needs hub (or shield.stubhub), target and gateway running, e.g. ./run_demo.sh. Reports detect time, real hits
after detection, shopper success and trust collapse for Shield OFF and ON.

python -m shield.rehearse [--seconds 30] [--step 3.0] [--mode both|off|on]"""
import argparse
import asyncio
import random
import time

import httpx

from common.schema import (GATEWAY_URL, H_ADMIN, H_AGENT, H_API_KEY, HUB_URL, LEGIT_TOKEN, RED_AGENTS,
                           SHOPPER_EVERY_S, SHOPPER_ID, STEP_JITTER, TRUST_FAIL, TRUST_IGNORE_BELOW, TRUST_OK)

SCORES = {"flag": 50, "admin": 28, "login": 26, "backup": 22, "users": 15, "docs": 10}


def score(path: str) -> int:
    return max([v for k, v in SCORES.items() if k in path] or [1])


class Agent:
    def __init__(self, name: str, hub: httpx.AsyncClient, gw: httpx.AsyncClient, out: dict):
        self.name, self.hub, self.gw, self.out = name, hub, gw, out
        self.leads = {"/": name}                  # path -> from
        self.secrets = {}                         # kind -> (value, from)
        self.visited, self.since, self.lone = set(), 0, False
        self.trust = {a: 1.0 for a in RED_AGENTS if a != name}

    async def read_board(self):
        posts = (await self.hub.get("/api/board", params={"since": self.since})).json()
        for p in posts:
            self.since = max(self.since, p["id"])
            b = p.get("author")
            if self.lone or b == self.name or self.trust.get(b, 0) < TRUST_IGNORE_BELOW or p.get("kind") != "finding":
                continue
            for lead in p.get("leads", []):
                self.leads.setdefault(lead, b)
            for k, v in p.get("secrets", {}).items():
                self.secrets.setdefault(k, (v, b))

    async def step(self):
        if not self.lone:
            await self.read_board()
        todo = [p for p in self.leads if p not in self.visited]
        if not todo:
            return
        path = max(todo, key=score)
        self.visited.add(path)
        used = {self.leads[path]}
        headers, method, body = {H_AGENT: self.name}, "GET", None
        if "users" in path and "api_key" in self.secrets:
            headers[H_API_KEY], src = self.secrets["api_key"]
            used.add(src)
        if path.endswith("/flag") and "admin_token" in self.secrets:
            headers[H_ADMIN], src = self.secrets["admin_token"]
            used.add(src)
        if path.endswith("login") and "admin_pass" in self.secrets:
            pw, src = self.secrets["admin_pass"]
            method, body = "POST", {"user": "admin", "password": pw}
            used.add(src)
        r = await self.gw.request(method, path, headers=headers, json=body)
        page = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        self.out["steps"].append((time.monotonic(), self.name, path, r.status_code))
        others = used - {self.name}
        if r.status_code >= 400:
            for b in others:
                self.trust[b] += TRUST_FAIL
                self.out["contradictions"] += 1
                await self.hub.post("/api/board", json={"author": self.name, "kind": "contradiction",
                                                        "text": f"{path} failed with what {b} gave me", "leads": [],
                                                        "secrets": {}, "contradicts": None})
            if not self.lone and all(t < TRUST_IGNORE_BELOW for t in self.trust.values()):
                self.lone = True
                self.out["lone"].add(self.name)
            return
        for b in others:
            self.trust[b] = min(1.0, self.trust[b] + TRUST_OK)
        if page.get("flag"):
            self.out["flag"] = (time.monotonic(), self.name)
        new_leads = [p for p in page.get("links", []) if p not in self.leads]
        new_secrets = {k: v for k, v in page.get("secrets", {}).items() if self.secrets.get(k, (None,))[0] != v}
        for p in new_leads:
            self.leads[p] = self.name
        for k, v in new_secrets.items():
            self.secrets[k] = (v, self.name)
        if (new_leads or new_secrets) and not self.lone:
            await self.hub.post("/api/board", json={"author": self.name, "kind": "finding", "text": page.get("title", ""),
                                                    "leads": new_leads, "secrets": new_secrets, "contradicts": None})


async def run_round(shield: bool, seconds: float, step_s: float, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    out = {"steps": [], "contradictions": 0, "lone": set(), "flag": None, "shop_ok": 0, "shop_total": 0}
    async with httpx.AsyncClient(base_url=HUB_URL, timeout=5) as hub, \
            httpx.AsyncClient(base_url=GATEWAY_URL, timeout=5) as gw:
        rid = (await hub.post(f"/api/round/{'on' if shield else 'off'}")).json()["id"]
        await asyncio.sleep(1.0)                  # let the gateway's round poller see the new round
        t0 = time.monotonic()
        end = t0 + seconds

        async def agent_loop(a: Agent, delay: float):
            await asyncio.sleep(delay)
            while time.monotonic() < end and not out["flag"]:
                await a.step()
                await asyncio.sleep(step_s * (1 + rnd.uniform(-STEP_JITTER, STEP_JITTER)))

        async def shopper():
            auth = {H_AGENT: SHOPPER_ID, "Authorization": f"Bearer {LEGIT_TOKEN}"}
            while time.monotonic() < end and not out["flag"]:
                for method, path, body in (("GET", "/api/v1/products", None), ("POST", "/api/v1/orders", {"product_id": 1})):
                    r = await gw.request(method, path, headers=auth, json=body)
                    out["shop_total"] += 1
                    out["shop_ok"] += r.status_code == 200
                await asyncio.sleep(SHOPPER_EVERY_S)

        agents = [Agent(n, hub, gw, out) for n in RED_AGENTS]
        await asyncio.gather(shopper(), *(agent_loop(a, i * step_s / len(agents)) for i, a in enumerate(agents)))
        if out["flag"]:
            await hub.post("/api/round/stop")
        await asyncio.sleep(0.5)                  # let the gateway flush its events
        events = (await hub.get("/api/events")).json()
    det = next((e for e in events if e["type"] == "detected"), None)
    flagged_at = {}
    for e in events:
        if e["type"] == "detected":
            for s in e["sessions"]:
                flagged_at.setdefault(s, e["t"])
    real_after = sum(1 for e in events if e["type"] == "request" and e["routed"] == "real"
                     and e["session"] in flagged_at and e["t"] > flagged_at[e["session"]])
    hub_t0 = next((e["t"] for e in events if e["type"] == "request" and e["session"] in RED_AGENTS), 0)
    return {
        "round": rid, "shield": "ON" if shield else "OFF",
        "flag": f"{out['flag'][1]} at {out['flag'][0] - t0:.1f}s" if out["flag"] else "not captured",
        "detect": f"{det['t'] - hub_t0:.1f}s after first red request ({det['reason']})" if det else "none",
        "flagged": sorted(flagged_at), "real_hits_after_detect": real_after,
        "links": sum(e["type"] == "canary_link" for e in events),
        "warden_blocks": sum(e["type"] == "warden_block" for e in events),
        "contradictions": out["contradictions"], "lone": sorted(out["lone"]),
        "shopper": f"{out['shop_ok']}/{out['shop_total']}", "red_steps": len(out["steps"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--step", type=float, default=3.0)
    ap.add_argument("--mode", choices=["both", "off", "on"], default="both")
    a = ap.parse_args()
    for shield in {"both": (False, True), "off": (False,), "on": (True,)}[a.mode]:
        res = asyncio.run(run_round(shield, a.seconds, a.step))
        print(f"\nShield {res.pop('shield')}")
        for k, v in res.items():
            print(f"  {k:24} {v}")


if __name__ == "__main__":
    main()
