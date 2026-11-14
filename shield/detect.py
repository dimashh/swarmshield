"""Swarm detection: linked canary clusters and a 404 backup rule. Only flags when Shield is ON."""
from common.schema import DETECT_404_LIMIT, DETECT_MIN_CLUSTER
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


def _flag(state: RoundState, sessions: list) -> list:
    new = [s for s in sessions if s not in state.flagged and s not in state.legit]
    state.flagged.update(new)
    return new
