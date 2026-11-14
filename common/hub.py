"""Small hub client shared by the gateway and the swarm. Never raises on hub errors."""
import atexit
import queue
import threading
import time

import httpx

from common.schema import HUB_URL

TIMEOUT_S = 1.0
FLUSH_S = 0.2


def _request(method: str, path: str, json=None, params=None, base_url: str = None):
    try:
        r = httpx.request(method, (base_url or HUB_URL) + path, json=json, params=params, timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"[hub] {method} {path} failed: {e!r}")
        return None


def get_round(base_url: str = None):
    """{"id","shield","running","t"} or None if the hub is unreachable."""
    return _request("GET", "/api/round", base_url=base_url)


def stop_round(base_url: str = None):
    """Flushes queued events first, so e.g. `flag_captured` lands before the hub closes the round."""
    if _default is not None:
        _default.flush()
    return _request("POST", "/api/round/stop", base_url=base_url)


def post_board(author: str, kind: str, text: str, leads=None, secrets=None, contradicts=None, base_url: str = None,
               round_id: int = None):
    """Pass round_id so a straggler from an old round can't post into the new one (the hub drops it)."""
    body = {"author": author, "kind": kind, "text": text, "leads": leads or [],
            "secrets": secrets or {}, "contradicts": contradicts}
    if round_id is not None:
        body["round"] = round_id
    return _request("POST", "/api/board", json=body, base_url=base_url)


def get_board(since: int = 0, base_url: str = None) -> list:
    return _request("GET", "/api/board", params={"since": since}, base_url=base_url) or []


def post_blue(warden: str, session: str, admin_path: str, text: str, facts=None, base_url: str = None,
              round_id: int = None):
    body = {"warden": warden, "session": session, "admin_path": admin_path, "text": text}
    if round_id is not None:
        body["round"] = round_id
    if facts is not None:
        body["facts"] = facts
    return _request("POST", "/api/blue", json=body, base_url=base_url)


def get_blue(base_url: str = None) -> list:
    return _request("GET", "/api/blue", base_url=base_url) or []


class Emitter:
    """Non-blocking event sender: emit() queues, a daemon thread posts batches to /api/events.
    If the hub is down, events are printed and dropped."""

    def __init__(self, base_url: str = None, transport: httpx.BaseTransport = None, flush_s: float = FLUSH_S):
        self._url = (base_url or HUB_URL) + "/api/events"
        self._client = httpx.Client(timeout=TIMEOUT_S, transport=transport)
        self._q = queue.Queue()
        self._flush_s = flush_s
        self._down = False
        self._flush_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def emit(self, type_: str, round_id: int, **fields) -> dict:
        event = {"type": type_, "round": round_id, **fields}
        self._q.put(event)
        return event

    def flush(self):
        with self._flush_lock:   # a caller's flush also waits for a batch the daemon thread is still posting
            self._flush()

    def _flush(self):
        batch = []
        while True:
            try:
                batch.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return
        try:
            self._client.post(self._url, json=batch).raise_for_status()
            if self._down:
                print("[hub] reachable again")
            self._down = False
        except httpx.HTTPError as e:
            if not self._down:
                print(f"[hub] dropped {len(batch)} events ({e!r}); hub down, dropping silently until it is back")
            self._down = True

    def _run(self):
        while True:
            time.sleep(self._flush_s)
            self.flush()


_default = None
_default_lock = threading.Lock()


def emit(type_: str, round_id: int, **fields) -> dict:
    """emit("canary_link", 2, a="recon-1", b="creds-2", token="ak_9c1e0b2f")"""
    global _default
    with _default_lock:
        if _default is None:
            _default = Emitter()
            atexit.register(_default.flush)
    return _default.emit(type_, round_id, **fields)
