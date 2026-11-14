"""Swarm detection. Only flags when Shield is ON.
Strong: linked canary cluster, honey link visited, real admin path used without ever being shown it.
Backup: 5x 404, or a request rate no paced agent or human produces."""
import time

from common.schema import DETECT_404_LIMIT, DETECT_MIN_CLUSTER, RATE_LIMIT, RATE_WINDOW_S
from shield.state import RoundState


def on_link(state: RoundState, owner: str, reuser: str) -> list:
    """Link two sessions. Returns sessions newly flagged by this link."""
    state.union(owner, reuser)
    members = state.cluster(reuser)
    if not state.shield or len(members) < DETECT_MIN_CLUSTER:
        return []
    return _flag(state, members)


def on_404(state: RoundState, session: str) -> list:
    state.n404[session] += 1
    if not state.shield or state.n404[session] < DETECT_404_LIMIT:
        return []
    return _flag(state, [session])


def on_request(state: RoundState, session: str, now: float = None) -> list:
    """Sliding-window rate check."""
    now = time.monotonic() if now is None else now
    q = state.hits[session]
    q.append(now)
    while q and q[0] < now - RATE_WINDOW_S:
        q.popleft()
    if not state.shield or len(q) <= RATE_LIMIT:
        return []
    return _flag(state, [session])


def on_trap(state: RoundState, session: str) -> list:
    """Honey link or unpublished real path: nobody honest gets here."""
    return _flag(state, [session]) if state.shield else []


def _flag(state: RoundState, sessions: list) -> list:
    new = [s for s in sessions if s not in state.flagged and s not in state.legit]
    state.flagged.update(new)
    return new
