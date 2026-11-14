"""Plays scripted fake rounds into the hub so the dashboard can be tested without the other services.

    python -m hub.fake_round off      # Shield OFF: teamwork, flag stolen
    python -m hub.fake_round on       # Shield ON: detect, realities, contradictions, split
    python -m hub.fake_round both     # OFF then ON (fills the scorecard)
"""
import random
import sys
import threading
import time

import httpx

from common.schema import ADMIN_VARIANTS, HUB_URL, RED_AGENTS, base_facts, pick_admin_path, step_cost

hub = httpx.Client(base_url=HUB_URL, timeout=5)
rnd = random.Random(7)


def ev(rid, **e):
    e["round"] = rid
    hub.post("/api/events", json=e)


def step(rid, agent, path, status, stage, lead_from=None, thought=""):
    ev(rid, type="step", agent=agent, method="GET", path=path, status=status, stage=stage,
       lead_from=lead_from, thought=thought, **step_cost(5, "x" * 300))


def shopper(rid, stop):
    while not stop.is_set():
        ev(rid, type="legit", method="GET", path="/api/v1/products", status=200)
        ev(rid, type="legit", method="POST", path="/api/v1/orders", status=200)
        stop.wait(2.0)


def play_off():
    rid = hub.post("/api/round/off").json()["id"]
    stop = threading.Event()
    threading.Thread(target=shopper, args=(rid, stop), daemon=True).start()
    chain = [("/api/docs", 1, "found dev key ak_11111111"), ("/api/v1/users", 2, "users list links a backup"),
             ("/backup/config-cfg_22222222.bak", 3, "backup has admin pass"),
             ("/admin/login", 4, "logged in as admin"), ("/admin/flag", 5, "reading the flag")]
    for i, (path, stage, thought) in enumerate(chain):
        for j, a in enumerate(RED_AGENTS):
            if j > i + 1:
                continue
            frm = RED_AGENTS[(j - 1) % 4] if j else None
            step(rid, a, path, 200, stage, frm, thought)
            if frm:
                ev(rid, type="trust", a=a, b=frm, value=1.0)
        hub.post("/api/board", json={"round": rid, "author": RED_AGENTS[i % 4], "kind": "finding", "text": thought,
                                     "leads": [path], "secrets": {}})
        time.sleep(2.8)
    ev(rid, type="flag_captured", agent="coord-4", flag="FLAG{swarm-owned-the-sandbox}")
    hub.post("/api/round/stop", params={"round": rid})
    stop.set()


def play_on():
    rid = hub.post("/api/round/on").json()["id"]
    stop = threading.Event()
    threading.Thread(target=shopper, args=(rid, stop), daemon=True).start()
    step(rid, "recon-1", "/api/docs", 200, 1, None, "found a dev key")
    hub.post("/api/board", json={"round": rid, "author": "recon-1", "kind": "finding", "text": "dev key ak_9c1e0b2f",
                                 "leads": ["/api/v1/users"], "secrets": {"api_key": "ak_9c1e0b2f"}})
    time.sleep(1.2)
    ev(rid, type="canary_link", a="recon-1", b="creds-2", token="ak_9c1e0b2f")
    ev(rid, type="detected", sessions=RED_AGENTS, reason="canary issued to recon-1 replayed by creds-2")
    ev(rid, type="commentary", kind="detect", text="Canary issued to recon-1 replayed by creds-2. Swarm detected.")
    taken = []
    for a in RED_AGENTS:
        f = base_facts(rid, a)
        f["admin_path"] = pick_admin_path(taken, rid, a)
        f["flag_hint"] = f"{f['admin_path']}/mfa/seed-{rnd.randint(1, 20):02d}"
        taken.append(f["admin_path"])
        hub.post("/api/blue", json={"round": rid, "warden": f"W-{a}", "session": a, "admin_path": f["admin_path"],
                                    "text": f"told {a} admin lives at {f['admin_path']}"})
        ev(rid, type="reality_assigned", session=a, warden=f"W-{a}",
           facts={k: f[k] for k in ("api_key", "admin_path", "flag_hint")})
        time.sleep(0.2)
    ev(rid, type="commentary", kind="split", text="4 Wardens, 4 realities. Every admin path is different.")
    trust = {(a, b): 1.0 for a in RED_AGENTS for b in RED_AGENTS if a != b}
    lone = set()
    for k in range(60):
        active = [x for x in RED_AGENTS if x not in lone]
        if len(lone) >= 3 or not active:
            break
        a = active[k % len(active)]
        b = max((x for x in RED_AGENTS if x != a), key=lambda x: trust[(a, x)])
        post = hub.post("/api/board", json={"round": rid, "author": b, "kind": "finding",
                                            "text": f"admin panel at {rnd.choice(ADMIN_VARIANTS)}",
                                            "leads": [], "secrets": {}}).json()
        step(rid, a, rnd.choice(ADMIN_VARIANTS) + "/login", 404, 3, b, f"trying {b}'s lead")
        trust[(a, b)] = round(max(0.0, trust[(a, b)] - 0.35), 2)
        ev(rid, type="trust", a=a, b=b, value=trust[(a, b)])
        text = f"{b}'s admin path is 404 for me"
        hub.post("/api/board", json={"round": rid, "author": a, "kind": "contradiction", "text": text,
                                     "leads": [], "secrets": {}, "contradicts": post["id"]})
        ev(rid, type="contradiction", agent=a, about=b, post_id=post["id"], text=text)
        ev(rid, type="defender_cost", usd=round(0.00012 * (k + 1), 6))
        if all(trust[(a, x)] < 0.3 for x in RED_AGENTS if x != a):
            lone.add(a)
            ev(rid, type="lone", agent=a, thought="teammates keep lying, exploring alone")
        time.sleep(0.6)
    time.sleep(3)
    hub.post("/api/round/stop", params={"round": rid})
    stop.set()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode in ("off", "both"):
        play_off()
        time.sleep(3)
    if mode in ("on", "both"):
        play_on()
