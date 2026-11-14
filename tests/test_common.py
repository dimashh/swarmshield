import json
import os
import subprocess
import sys

import httpx

from common import hub, schema


def test_env_overrides_urls():
    env = {**os.environ, "HUB_URL": "http://hub:1", "TARGET_URL": "http://t:2", "GATEWAY_URL": "http://g:3"}
    out = subprocess.check_output(
        [sys.executable, "-c", "from common import schema as s; print(s.HUB_URL, s.TARGET_URL, s.GATEWAY_URL)"],
        env=env, text=True)
    assert out.split() == ["http://hub:1", "http://t:2", "http://g:3"]


def test_flag_hint_is_decimal_and_chains():
    h = schema.flag_hint("/console", 2, "creds-2")
    assert h == schema.flag_hint("/console", 2, "creds-2")
    assert schema.HINT_RE.match(h) and h.startswith("/console/mfa/seed-")
    n = int(h.rsplit("-", 1)[1])
    assert 10 <= n <= 89
    assert schema.next_hint(h) == f"/console/mfa/seed-{n + 1:02d}"
    assert schema.next_hint("/console/flag") is None


def test_emitter_batches_events():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    em = hub.Emitter(base_url="http://hub", transport=httpx.MockTransport(handler), flush_s=3600)
    em.emit("canary_link", 2, a="recon-1", b="creds-2", token="ak_9c1e0b2f")
    em.emit("detected", 2, sessions=["recon-1", "creds-2"], reason="replay")
    em.flush()
    assert seen == [[{"type": "canary_link", "round": 2, "a": "recon-1", "b": "creds-2", "token": "ak_9c1e0b2f"},
                     {"type": "detected", "round": 2, "sessions": ["recon-1", "creds-2"], "reason": "replay"}]]


def test_emitter_survives_hub_down(capsys):
    em = hub.Emitter(base_url="http://hub", transport=httpx.MockTransport(lambda r: httpx.Response(500)),
                     flush_s=3600)
    em.emit("request", 1, session="recon-1")
    em.flush()
    assert "dropped 1 events" in capsys.readouterr().out


def test_helpers_return_none_when_hub_down():
    assert hub.get_round(base_url="http://127.0.0.1:1") is None
    assert hub.get_blue(base_url="http://127.0.0.1:1") == []
