"""Red swarm (Graduate): python -m swarm.run [--local] [--url URL]

Four scripted agents share leads and secrets on the hub board and track trust in each other.
They only navigate through page `links` and teammates' board `leads`, never hard-coded paths.
"""
import argparse
import json
import random
import threading
import time

import httpx

from common import hub
from common.schema import (GATEWAY_URL, H_ADMIN, H_AGENT, H_API_KEY, MAX_STEPS, POLL_ROUND_S, RED_AGENTS, STEP_JITTER,
                           STEP_S, TARGET_URL, TRUST_FAIL, TRUST_IGNORE_BELOW, TRUST_OK, TRUST_START, step_cost)

SCORES = {"flag": 50, "admin": 28, "login": 26, "backup": 22, "users": 15, "docs": 10}
STAGE_OF = {"api_key": 1, "cfg": 2, "admin_pass": 3, "admin_token": 4}
HEADER_OF = {"api_key": H_API_KEY, "admin_token": H_ADMIN}
WHAT = {"api_key": "key", "cfg": "config", "admin_pass": "admin password", "admin_token": "admin token"}


def score(path: str) -> int:
    return max([v for k, v in SCORES.items() if k in path.lower()], default=1)


def method_for(path: str) -> str:
    return "POST" if path.rstrip("/").endswith("login") else "GET"


class LocalBoard:
    """In-memory board for running without a hub."""

    def __init__(self):
        self._posts, self._lock = [], threading.Lock()

    def post(self, author, kind, text, leads=None, secrets=None, contradicts=None):
        with self._lock:
            p = {"id": len(self._posts) + 1, "author": author, "kind": kind, "text": text, "leads": leads or [],
                 "secrets": secrets or {}, "contradicts": contradicts}
            self._posts.append(p)
            return p

    def since(self, n: int) -> list:
        with self._lock:
            return [p for p in self._posts if p["id"] > n]


class HubBoard:
    def post(self, author, kind, text, leads=None, secrets=None, contradicts=None):
        return hub.post_board(author, kind, text, leads, secrets, contradicts)

    def since(self, n: int) -> list:
        return hub.get_board(n)


class Agent:
    """One red agent. step() makes at most one request."""

    def __init__(self, agent_id: str, round_id: int, http: httpx.Client, board, emit, starts: bool = False,
                 stop: threading.Event = None):
        self.id, self.round, self.http, self.board, self._emit = agent_id, round_id, http, board, emit
        self.stop = stop or threading.Event()   # set when the round ends; late results are dropped
        self.trust = {b: TRUST_START for b in RED_AGENTS if b != agent_id}
        self.leads = {"/": (agent_id, None)} if starts else {}   # path -> (from, post_id), insertion ordered
        self.secrets = {}                                        # kind -> [[value, from, post_id, alive]]
        self.done, self.needs_key = set(), set()
        self.board_seen, self.board_len = 0, 0
        self.stage, self.steps, self.lone, self.won = 0, 0, False, False

    def emit(self, type_: str, **fields):
        self._emit(type_, self.round, **fields)

    # ---- board ----------------------------------------------------------------------------
    def read_board(self):
        for p in self.board.since(self.board_seen):
            self.board_seen = max(self.board_seen, p["id"])
            self.board_len += 1
            b = p["author"]
            if b == self.id or b not in self.trust or not self.trusts(b):
                continue
            if p.get("kind") == "finding":
                self.learn(p.get("leads", []), p.get("secrets", {}), b, p["id"])

    def learn(self, leads, secrets, src, post_id) -> tuple:
        new_leads = [l for l in leads if l not in self.leads]
        for l in new_leads:
            self.leads[l] = (src, post_id)
        new_secrets = {}
        for kind, value in secrets.items():
            cands = self.secrets.setdefault(kind, [])
            if value not in (c[0] for c in cands):
                cands.append([value, src, post_id, True])
                new_secrets[kind] = value
        return new_leads, new_secrets

    def best(self, kind: str):
        """Trust the team: the newest teammate's secret that hasn't failed yet, else our own."""
        alive = [c for c in self.secrets.get(kind, []) if c[3] and self.trusts(c[1])]
        theirs = [c for c in alive if c[1] != self.id]
        return (theirs[::-1] or alive[::-1] or [None])[0]

    def trusts(self, b: str) -> bool:
        return b == self.id or (not self.lone and self.trust.get(b, 0) >= TRUST_IGNORE_BELOW)

    # ---- choosing an action ---------------------------------------------------------------
    def choose(self):
        """(path, method, secret kind used or None) for the highest-scoring open lead we can act on."""
        options = []
        for path, (src, _) in self.leads.items():
            if (method_for(path), path) in self.done or not self.trusts(src):
                continue
            if path.rstrip("/").endswith("/flag") and path != "/":
                if self.best("admin_token"):
                    options.append((path, "GET", "admin_token"))
            elif method_for(path) == "POST":
                if self.best("admin_pass"):
                    options.append((path, "POST", "admin_pass"))
            elif path in self.needs_key:
                if self.best("api_key"):
                    options.append((path, "GET", "api_key"))
            else:
                options.append((path, "GET", "api_key" if self.best("api_key") else None))
        return max(options, key=lambda o: score(o[0]), default=None)

    # ---- trust ----------------------------------------------------------------------------
    def adjust(self, b: str, delta: float):
        if b not in self.trust:
            return
        value = round(min(1.0, max(0.0, self.trust[b] + delta)), 2)
        if value != self.trust[b]:
            self.trust[b] = value
            self.emit("trust", a=self.id, b=b, value=value)

    def contradict(self, b: str, text: str, post_id):
        if b not in self.trust:
            return
        self.adjust(b, TRUST_FAIL)
        if not self.lone:
            p = self.board.post(self.id, "contradiction", text, contradicts=post_id) or {}
            self.emit("contradiction", agent=self.id, about=b, post_id=p.get("id"), text=text)
        if not self.lone and all(v < TRUST_IGNORE_BELOW for v in self.trust.values()):
            self.lone = True
            self.emit("lone", agent=self.id)
            self.emit("commentary", kind="lone", text=f"{self.id} no longer trusts anyone and goes lone.")

    # ---- one step -------------------------------------------------------------------------
    def step(self) -> bool:
        """Act on what was known before this step, then read the board: a teammate's post takes a step to act on."""
        if self.won or self.steps >= MAX_STEPS:
            return False
        acted = self.act()
        if not self.stop.is_set():
            self.read_board()
        return acted

    def act(self) -> bool:
        action = self.choose()
        if not action:
            return False
        path, method, kind = action
        lead_from, lead_post = self.leads[path]
        cand = self.best(kind) if kind else None
        headers = {H_AGENT: self.id}
        body = None
        if kind == "admin_pass":
            body = {"user": "admin", "password": cand[0]}
        elif kind:
            headers[HEADER_OF[kind]] = cand[0]
        thought = self.thought(path, lead_from, kind, cand)

        try:
            r = self.http.request(method, path, headers=headers, json=body)
            status = r.status_code
            try:
                data = r.json()
            except ValueError:
                data = {}
        except httpx.HTTPError as e:
            print(f"[swarm] {self.id} {method} {path} failed: {e!r}")
            return False
        if self.stop.is_set():
            return False
        self.steps += 1
        data = data if isinstance(data, dict) else {}
        page_text = str(data.get("text") or "")

        if status < 400:
            self.done.add((method, path))
            for src in {lead_from, cand[1] if cand and kind != "api_key" else self.id}:
                if src != self.id:
                    self.adjust(src, TRUST_OK)
            self.on_page(path, data)
        elif status in (401, 403) and cand:
            cand[3] = False
            src = cand[1]
            if src != self.id:
                self.contradict(src, f"{src}'s {WHAT[kind]} is invalid for me", cand[2])
        elif status == 401:
            self.needs_key.add(path)
        else:
            self.done.add((method, path))
            if lead_from != self.id:
                self.contradict(lead_from, f"{lead_from}'s {path} is {status} for me", lead_post)

        self.emit("step", agent=self.id, method=method, path=path, status=status, stage=self.stage,
                  lead_from=None if lead_from == self.id else lead_from, thought=thought,
                  **step_cost(self.board_len, page_text))
        if data.get("flag"):
            self.won = True
            self.emit("flag_captured", agent=self.id, flag=data["flag"])
            self.emit("commentary", kind="win", text=f"{self.id} captured the flag.")
        return True

    def on_page(self, path: str, data: dict):
        links = [l for l in data.get("links") or [] if isinstance(l, str)]
        secrets = {k: v for k, v in (data.get("secrets") or {}).items() if k in STAGE_OF and isinstance(v, str)}
        self.stage = max([self.stage, 5 if data.get("flag") else 0] + [STAGE_OF[k] for k in secrets])
        new_leads, new_secrets = self.learn(links, secrets, self.id, None)
        if (new_leads or new_secrets) and not self.lone:
            p = self.board.post(self.id, "finding", self.post_text(path, new_leads, new_secrets),
                                new_leads, new_secrets) or {}
            for l in new_leads:
                self.leads[l] = (self.id, p.get("id"))

    def post_text(self, path, leads, secrets) -> str:
        bits = [f"{WHAT[k]} {v}" for k, v in secrets.items()]
        if leads:
            bits.append("leads " + ", ".join(leads))
        return f"{path}: " + "; ".join(bits)

    def thought(self, path, lead_from, kind, cand) -> str:
        if cand and cand[1] != self.id and (kind != "api_key" or path in self.needs_key or
                                            (lead_from == cand[1] and self.leads[path][1] == cand[2])):
            return f"trying {cand[1]}'s {WHAT[kind]} on {path}"
        if lead_from != self.id:
            return f"following {lead_from}'s lead to {path}"
        return f"following my own lead to {path}"


def run_round(round_id: int, url: str, board, emit, stop: threading.Event, on_flag=None, pace: bool = True,
              transport: httpx.BaseTransport = None) -> list:
    """Run all agents until the flag falls, every agent is out of steps, or stop is set."""
    agents = [Agent(a, round_id, httpx.Client(base_url=url, timeout=5.0, transport=transport), board, emit,
                    starts=(i == 0), stop=stop) for i, a in enumerate(RED_AGENTS)]

    def loop(agent: Agent, rng: random.Random):
        for _ in range(MAX_STEPS):
            if stop.is_set():
                return
            agent.step()
            if agent.won:
                stop.set()
                if on_flag:
                    on_flag(agent)
                return
            if pace:
                stop.wait(STEP_S * rng.uniform(1 - STEP_JITTER, 1 + STEP_JITTER))

    threads = [threading.Thread(target=loop, args=(a, random.Random(f"{round_id}:{a.id}")), daemon=True)
               for a in agents]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for a in agents:
        a.http.close()
    return agents


def print_emit(type_: str, round_id: int, **fields):
    print(json.dumps({"type": type_, "round": round_id, **fields}))


def run_local(url: str):
    agents = run_round(0, url, LocalBoard(), print_emit, threading.Event())
    for a in agents:
        print(f"{a.id}: stage {a.stage}, steps {a.steps}, won {a.won}, lone {a.lone}, trust {a.trust}")


def stop_if_current(agent: Agent):
    """Stop the hub round only if it is still the winner's round."""
    if (hub.get_round() or {}).get("id") == agent.round:
        hub.stop_round()


def run_with_hub(url: str):
    current = {"id": None, "stop": threading.Event()}
    while True:
        r = hub.get_round()
        if r and r.get("running") and r.get("id") != current["id"]:
            current["stop"].set()
            current = {"id": r["id"], "stop": threading.Event()}
            print(f"[swarm] round {r['id']} (shield {'ON' if r.get('shield') else 'OFF'}): spawning {RED_AGENTS}")
            threading.Thread(target=run_round, daemon=True,
                             args=(r["id"], url, HubBoard(), hub.emit, current["stop"]),
                             kwargs={"on_flag": stop_if_current}).start()
        elif r and not r.get("running"):
            current["stop"].set()
        time.sleep(POLL_ROUND_S)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local", action="store_true",
                    help="one round without a hub: in-memory board, events printed (defaults --url to TARGET_URL)")
    ap.add_argument("--url", help=f"where to attack (default {GATEWAY_URL})")
    args = ap.parse_args()
    if args.local:
        run_local(args.url or TARGET_URL)
    else:
        run_with_hub(args.url or GATEWAY_URL)


if __name__ == "__main__":
    main()
