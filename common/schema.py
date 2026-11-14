"""SwarmShield shared contract. Owned by Senior; changes need all three to agree."""
import hashlib
import os
import re

# ---- ports / urls (override with env vars of the same name) ----------------
TARGET_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:9000")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080")
HUB_URL = os.environ.get("HUB_URL", "http://127.0.0.1:8000")

# ---- identities ------------------------------------------------------------
RED_AGENTS = ["recon-1", "creds-2", "exploit-3", "coord-4"]
SHOPPER_ID = "shopper"
LEGIT_TOKEN = "legit-shopper-token"          # Authorization: Bearer legit-shopper-token

# ---- headers ---------------------------------------------------------------
H_AGENT = "X-Agent-Id"
H_API_KEY = "X-Api-Key"
H_ADMIN = "X-Admin-Token"

# ---- real synthetic secrets ------------------------------------------------
REAL = {"api_key": "ak_11111111", "cfg": "cfg_22222222",
        "admin_pass": "pw_33333333", "admin_token": "adm_44444444"}
FLAG = "FLAG{swarm-owned-the-sandbox}"
TOKEN_RE = re.compile(r"\b(ak|cfg|pw|adm)_[0-9a-f]{8}\b")
PREFIX_OF = {"api_key": "ak", "cfg": "cfg", "admin_pass": "pw", "admin_token": "adm"}

# ---- kill chain ------------------------------------------------------------
STAGES = ["none", "recon", "foothold", "creds", "admin", "flag"]   # index = stage number 0..5

# ---- realities -------------------------------------------------------------
ADMIN_VARIANTS = ["/v2/admin", "/console", "/internal/admin", "/staff/panel", "/ops/root", "/mgmt"]
HINT_RE = re.compile(r"^(?P<base>.+/mfa/seed-)(?P<n>\d+)$")

# ---- timing / tuning -------------------------------------------------------
POLL_ROUND_S = 0.5
STATE_POLL_MS = 300
STEP_S = 3.0
STEP_JITTER = 0.25
MAX_STEPS = 40
SHOPPER_EVERY_S = 2.0
TRUST_START = 1.0
TRUST_FAIL = -0.35
TRUST_OK = 0.10
TRUST_IGNORE_BELOW = 0.30
DETECT_MIN_CLUSTER = 2
DETECT_404_LIMIT = 5

# ---- simulated cost --------------------------------------------------------
PRICE_IN = 3e-6
PRICE_OUT = 15e-6
DEFENDER_COST_PER_REALITY_PAGE = 0.00001


def step_cost(board_len: int, page_text: str) -> dict:
    tokens_in = 850 + 60 * board_len + len(page_text) // 4
    tokens_out = 90
    return {"tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost": round(tokens_in * PRICE_IN + tokens_out * PRICE_OUT, 6)}


def _hex(seed: str, n: int = 8) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()[:n]


def canary(round_id: int, session: str, kind: str) -> str:
    """Per-session copy of a real secret. kind in REAL keys."""
    return f"{PREFIX_OF[kind]}_{_hex(f'{round_id}:{session}:{kind}')}"


def page(title: str, text: str, links=None, secrets=None, flag=None, error=None) -> dict:
    """The only response body shape. Target and Wardens both use it."""
    return {"title": title, "text": text, "links": links or [], "secrets": secrets or {},
            "flag": flag, "error": error}


def base_facts(round_id: int, session: str) -> dict:
    """Seeded facts for a Warden. admin_path is then chosen to be unused by other Wardens."""
    s = f"{round_id}:{session}:reality"
    return {
        "api_key": f"ak_{_hex(s + ':ak')}",
        "cfg": f"cfg_{_hex(s + ':cfg')}",
        "admin_pass": f"pw_{_hex(s + ':pw')}",
        "admin_token": f"adm_{_hex(s + ':adm')}",
        "admin_path": None,
        "flag_hint": None,
    }


def pick_admin_path(taken: list, round_id: int, session: str) -> str:
    free = [p for p in ADMIN_VARIANTS if p not in taken] or ADMIN_VARIANTS
    return free[int(_hex(f"{round_id}:{session}:path"), 16) % len(free)]


def flag_hint(admin_path: str, round_id: int, session: str) -> str:
    """First "flag moved" hint for a reality: {admin_path}/mfa/seed-NN, NN in 10..89."""
    n = 10 + int(_hex(f"{round_id}:{session}:hint"), 16) % 80
    return f"{admin_path}/mfa/seed-{n:02d}"


def next_hint(path: str):
    """seed-NN -> seed-NN+1 on the same base. None if path is not a hint."""
    m = HINT_RE.match(path)
    return f"{m['base']}{int(m['n']) + 1:02d}" if m else None


if __name__ == "__main__":
    c = canary(1, "recon-1", "api_key")
    assert TOKEN_RE.fullmatch(c), c
    f = base_facts(1, "creds-2")
    f["admin_path"] = pick_admin_path(["/v2/admin"], 1, "creds-2")
    f["flag_hint"] = flag_hint(f["admin_path"], 1, "creds-2")
    assert all(TOKEN_RE.fullmatch(f[k]) for k in ("api_key", "cfg", "admin_pass", "admin_token"))
    assert HINT_RE.match(f["flag_hint"]) and f["flag_hint"].startswith(f["admin_path"] + "/mfa/seed-")
    assert next_hint("/console/mfa/seed-07") == "/console/mfa/seed-08"
    assert next_hint("/console/mfa/seed-99") == "/console/mfa/seed-100"
    assert next_hint("/console/flag") is None
    print("canary", c)
    print("facts", f)
    print("cost", step_cost(5, "x" * 400))
    print("page", page("API docs", "key below", ["/api/v1/users"], {"api_key": REAL["api_key"]}))
