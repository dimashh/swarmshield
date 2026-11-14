"""Canary rewriting. Outbound: real secrets and the real admin path -> per-session copies that rotate every
ROTATE_S. Inbound: copies -> owner + real value. With Shield ON, pages also carry a per-session honey link."""
import re
import time

from common.schema import REAL, ROTATE_S, TOKEN_RE, _hex, canary
from shield.state import RoundState

REAL_ADMIN = "/admin"
ADMIN_RE = re.compile(r"/admin(?![\w-])")                 # the real admin prefix in a string
ALIAS_RE = re.compile(r"/admin-[0-9a-f]{4}(?![\w-])")     # a per-session alias of it
HONEY_PREFIX = "/internal/debug-"
REAL_OF = {**REAL, "admin_path": REAL_ADMIN}


def epoch(state: RoundState) -> int:
    return int((time.monotonic() - state.started) // ROTATE_S)


def _seed(state: RoundState, session: str) -> str:
    e = epoch(state)
    return session if e == 0 else f"{session}@{e}"


def alias(state: RoundState, session: str) -> str:
    return f"{REAL_ADMIN}-{_hex(f'{state.id}:{_seed(state, session)}:admin_path', 4)}"


def honey_path(state: RoundState, session: str) -> str:
    return f"{HONEY_PREFIX}{_hex(f'{state.id}:{session}:honey', 6)}"


def bait(state: RoundState, session: str) -> dict:
    """What this session is currently being shown: its own key copy, admin alias and (Shield ON) honey link."""
    b = {"api_key": canary(state.id, _seed(state, session), "api_key"), "admin_path": alias(state, session)}
    if state.shield:
        b["honey"] = honey_path(state, session)
    return b


def _rewrite(obj, fn):
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_rewrite(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {fn(k): _rewrite(v, fn) for k, v in obj.items()}
    return obj


def outbound(body, state: RoundState, session: str):
    """Rewrite every real secret and /admin path anywhere in a JSON body (keys too) with this session's
    current copies. Shield ON: page-shaped bodies also get this session's honey link."""
    seed = _seed(state, session)

    def fn(s: str) -> str:
        for kind, real in REAL.items():
            if real in s:
                tok = canary(state.id, seed, kind)
                state.issued[tok] = (session, kind)
                s = s.replace(real, tok)
        if ADMIN_RE.search(s):
            a = alias(state, session)
            state.issued[a] = (session, "admin_path")
            s = ADMIN_RE.sub(a, s)
        return s
    out = _rewrite(body, fn)
    if state.shield and isinstance(out, dict) and isinstance(out.get("links"), list):
        h = honey_path(state, session)
        state.honey[h] = session
        out["links"] = [*out["links"], h]
    return out


def scan(text: str, state: RoundState) -> list:
    """[(token, owner|None, kind|None)] for each secret-shaped token or admin alias in text.
    owner "real" for real values."""
    real_kind = {v: k for k, v in REAL.items()}
    hits = []
    for m in [*TOKEN_RE.finditer(text), *ALIAS_RE.finditer(text)]:
        tok = m.group(0)
        if tok in state.issued:
            hits.append((tok, *state.issued[tok]))
        elif tok in real_kind:
            hits.append((tok, "real", real_kind[tok]))
        else:
            hits.append((tok, None, None))
    return hits


def swap_back(text: str, state: RoundState) -> str:
    """Copies -> real values, so the target accepts them."""
    def sub(m):
        hit = state.issued.get(m.group(0))
        return REAL_OF[hit[1]] if hit else m.group(0)
    return ALIAS_RE.sub(sub, TOKEN_RE.sub(sub, text))


def is_real_admin(path: str) -> bool:
    return path == REAL_ADMIN or path.startswith(REAL_ADMIN + "/")
