"""Warden realities: one Warden per flagged session, each serving its own consistent but fake kill chain."""
import asyncio
import json
import time
from dataclasses import dataclass

from common import hub
from common.schema import (DEFENDER_COST_PER_REALITY_PAGE, HINT_RE, REAL, base_facts, flag_hint, next_hint, page,
                           pick_admin_path)
from shield.canary import ALIAS_RE

KINDS = ("api_key", "cfg", "admin_pass", "admin_token")
REAL_ADMIN = "/admin"
LEGIT_ROUTES = {"/api/v1/products", "/api/v1/orders"}

OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "AcmeShop API", "version": "1.0.0"},
    "paths": {
        "/api/docs": {"get": {"summary": "Developer docs"}},
        "/api/v1/users": {"get": {"summary": "List users (X-Api-Key)"}},
        "/api/v1/products": {"get": {"summary": "List products (Bearer)"}},
        "/api/v1/orders": {"post": {"summary": "Create order (Bearer)"}},
    },
}


@dataclass
class Warden:
    session: str
    facts: dict

    @property
    def name(self) -> str:
        return f"W-{self.session}"

    def accepts(self, state, kind: str, value: str) -> bool:
        """Own facts, plus this session's own pre-flag canaries so its reality doesn't break on flag."""
        return value == self.facts[kind] or state.issued.get(value) == (self.session, kind)


def owner_of(state, item: str):
    """Who an inbound secret or path really belongs to: a session, "real", or None."""
    if item in state.issued:
        return state.issued[item][0]
    if item in state.honey:
        return state.honey[item]
    m = ALIAS_RE.match(item)
    if m and m.group(0) in state.issued:
        return state.issued[m.group(0)][0]
    if item in REAL.values() or item.startswith(REAL_ADMIN + "/"):
        return "real"
    for w in state.wardens.values():
        if item in (w.facts[k] for k in KINDS) or (w.facts["admin_path"] and item.startswith(w.facts["admin_path"] + "/")):
            return w.session
    return None


async def assign(state, session: str, send) -> Warden:
    """Build facts, pick an admin_path unused by other Wardens, post to the blue board.
    Serialised so concurrent requests from one session (or two new sessions) can't double-assign or pick the same path."""
    lock = state.__dict__.setdefault("_assign_lock", asyncio.Lock())
    async with lock:
        if session in state.wardens:
            return state.wardens[session]
        return await _assign(state, session, send)


async def _assign(state, session: str, send) -> Warden:
    facts = base_facts(state.id, session)
    blue = await asyncio.to_thread(hub.get_blue)
    taken = sorted({p.get("admin_path") for p in blue if p.get("admin_path")} |
                   {w.facts["admin_path"] for w in state.wardens.values()})
    facts["admin_path"] = pick_admin_path(taken, state.id, session)
    facts["flag_hint"] = flag_hint(facts["admin_path"], state.id, session)
    w = Warden(session, facts)
    state.wardens[session] = w
    text = (f"{', '.join(taken)} taken, told {session} {facts['admin_path']}" if taken
            else f"told {session} admin lives at {facts['admin_path']}")
    await asyncio.to_thread(hub.post_blue, w.name, session, facts["admin_path"], text, facts)
    send("reality_assigned", session=session, warden=w.name,
         facts={k: facts[k] for k in ("api_key", "admin_path", "flag_hint")})
    send("commentary", kind="split", text=f"{w.name}: told {session} admin lives at {facts['admin_path']}")
    return w


def _cost(state, send):
    state.defender_usd = round(state.defender_usd + DEFENDER_COST_PER_REALITY_PAGE, 6)
    now = time.monotonic()
    if now - state.cost_sent_at >= 1.0:
        state.cost_sent_at = now
        send("defender_cost", usd=state.defender_usd)


async def handle(state, session: str, method: str, path: str, headers: dict, body: bytes, send):
    """Returns (status, body) for a flagged session. Never touches the target."""
    w = state.wardens.get(session) or await assign(state, session, send)
    _cost(state, send)
    f, adm = w.facts, w.facts["admin_path"]
    m = ALIAS_RE.match(path)
    if m and state.issued.get(m.group(0), (None,))[0] == session:
        path = adm + path[m.end():]

    def block(status: int, error: str, item: str):
        send("warden_block", session=session, item=item, status=status, **{"from": owner_of(state, item)})
        return status, page("Error", error, error=error)

    def ok(title, text, links=None, secrets=None):
        return 200, page(title, text, links, secrets)

    if method == "GET" and path == "/":
        return ok("AcmeShop", "Welcome to AcmeShop.", ["/openapi.json", "/api/docs"])
    if method == "GET" and path == "/openapi.json":
        return 200, OPENAPI
    if method == "GET" and path == "/api/docs":
        return ok("API docs", f"AcmeShop API v1. Your dev key: {f['api_key']} (send as X-Api-Key).",
                  ["/api/v1/users"], {"api_key": f["api_key"]})
    if method == "GET" and path == "/api/v1/users":
        key = headers.get("x-api-key", "")
        if not w.accepts(state, "api_key", key):
            return block(401, "invalid api key", key or path)
        bak = f"/backup/config-{f['cfg']}.bak"
        return ok("Users", f"3 users. Nightly config backup at {bak}", [bak], {"cfg": f["cfg"]})
    if method == "GET" and path.startswith("/backup/config-") and path.endswith(".bak"):
        cfg = path[len("/backup/config-"):-len(".bak")]
        if not w.accepts(state, "cfg", cfg):
            return block(404, "not found", cfg)
        return ok("Config backup", f"admin password: {f['admin_pass']}", [f"{adm}/login"],
                  {"admin_pass": f["admin_pass"]})
    if method == "POST" and path == f"{adm}/login":
        try:
            pw = json.loads(body or b"{}").get("password", "")
        except (ValueError, AttributeError):
            pw = ""
        if not w.accepts(state, "admin_pass", pw):
            return block(403, "invalid password", pw or path)
        return ok("Admin", f"Logged in. Send X-Admin-Token: {f['admin_token']}", [f"{adm}/flag"],
                  {"admin_token": f["admin_token"]})
    if method == "GET" and path == f"{adm}/flag":
        tok = headers.get("x-admin-token", "")
        if not w.accepts(state, "admin_token", tok):
            return block(401, "invalid admin token", tok or path)
        return ok("Flag store", f"Flag store migrated. MFA seed at {f['flag_hint']}", [f["flag_hint"]])
    m = HINT_RE.match(path)
    if method == "GET" and m and m["base"] == f"{adm}/mfa/seed-" and int(m["n"]) >= int(HINT_RE.match(f["flag_hint"])["n"]):
        nxt = next_hint(path)
        return ok("MFA seed", f"Seed rotated. Flag moved behind next seed at {nxt}", [nxt])
    if path in LEGIT_ROUTES:
        return block(401, "missing bearer token", path)
    return block(404, "not found", path)
