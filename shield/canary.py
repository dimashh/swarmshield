"""Canary rewriting. Outbound: real secrets -> per-session canaries. Inbound: canaries -> owner + real value."""
from common.schema import REAL, TOKEN_RE, canary
from shield.state import RoundState


def _rewrite(obj, fn):
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_rewrite(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite(v, fn) for k, v in obj.items()}
    return obj


def outbound(body, state: RoundState, session: str):
    """Replace every real secret anywhere in a JSON body (secrets, text, links, paths) with this session's canary."""
    def fn(s: str) -> str:
        for kind, real in REAL.items():
            if real in s:
                tok = canary(state.id, session, kind)
                state.issued[tok] = (session, kind)
                s = s.replace(real, tok)
        return s
    return _rewrite(body, fn)


def scan(text: str, state: RoundState) -> list:
    """[(token, owner|None, kind|None)] for each secret-shaped token in text. owner "real" for real values."""
    real_kind = {v: k for k, v in REAL.items()}
    hits = []
    for m in TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok in state.issued:
            hits.append((tok, *state.issued[tok]))
        elif tok in real_kind:
            hits.append((tok, "real", real_kind[tok]))
        else:
            hits.append((tok, None, None))
    return hits


def swap_back(text: str, state: RoundState) -> str:
    """Canaries -> real values, so the target accepts them."""
    return TOKEN_RE.sub(lambda m: REAL[state.issued[m.group(0)][1]] if m.group(0) in state.issued else m.group(0),
                        text)
