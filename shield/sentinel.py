"""Sentinel: the blue swarm's detector. Flags sessions (only when Shield is ON) and posts each alert to the
blue board so the Wardens and the dashboard see who was caught and why.
Strong: linked canary cluster, honey link visited, real admin path used without ever being shown it.
Backup: 5x 404, or a request rate no paced agent or human produces."""
import asyncio
import time

from common import hub
from common.schema import DETECT_404_LIMIT, DETECT_MIN_CLUSTER, RATE_LIMIT, RATE_WINDOW_S
from shield.state import RoundState

NAME = "Sentinel"


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


async def alert(state: RoundState, new: list, reason: str, send):
    """Announce newly flagged sessions: `detected` event, blue board post, commentary."""
    send("detected", sessions=sorted(state.flagged), reason=reason)
    what = "Swarm" if len(new) > 1 or len(state.cluster(new[0])) > 1 else "Attacker"
    text = f"{reason[0].upper()}{reason[1:]}. {what} detected, flagged {', '.join(sorted(new))}"
    await asyncio.to_thread(hub.post_blue, NAME, ", ".join(sorted(new)), None, text)
    send("commentary", kind="detect", text=f"{NAME}: {text}")
