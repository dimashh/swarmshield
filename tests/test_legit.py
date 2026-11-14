import threading

import httpx
from fastapi.testclient import TestClient

from common.schema import LEGIT_TOKEN, SHOPPER_ID
from swarm.legit import UNREACHABLE, run_shopper, shop_once
from target.app import app as target_app


def collect(events):
    return lambda t, **f: events.append({"type": t, **f})


def test_shopper_lists_then_orders_on_real_target():
    events = []
    with TestClient(target_app) as http:
        assert shop_once(http, collect(events))
    assert events == [{"type": "legit", "method": "GET", "path": "/api/v1/products", "status": 200},
                      {"type": "legit", "method": "POST", "path": "/api/v1/orders", "status": 200}]


def test_shopper_sends_bearer_and_id_and_orders_listed_product():
    seen = []

    def gw(request):
        seen.append(request)
        if request.url.path == "/api/v1/products":
            return httpx.Response(200, json={"items": [{"id": 7, "name": "Hat", "price": 5}]})
        return httpx.Response(200, json={"order_id": 1, "status": "created"})

    with httpx.Client(base_url="http://gw", transport=httpx.MockTransport(gw)) as http:
        assert shop_once(http, collect([]))
    assert all(r.headers["Authorization"] == f"Bearer {LEGIT_TOKEN}" and r.headers["X-Agent-Id"] == SHOPPER_ID
               for r in seen)
    assert seen[1].method == "POST" and seen[1].read() == b'{"product_id":7}'


def test_unreachable_gateway_counts_as_failure():
    def down(request):
        raise httpx.ConnectError("refused")

    events = []
    with httpx.Client(base_url="http://gw", transport=httpx.MockTransport(down)) as http:
        assert not shop_once(http, collect(events))
    assert [e["status"] for e in events] == [UNREACHABLE, UNREACHABLE]


def test_run_shopper_repeats_until_stopped_and_stamps_round():
    events, stop = [], threading.Event()

    def gw(request):
        if len(events) >= 4:
            stop.set()
        return httpx.Response(200, json={"items": [{"id": 1}]})

    run_shopper(5, "http://gw", lambda t, r, **f: events.append({"type": t, "round": r, **f}), stop, every=0,
                transport=httpx.MockTransport(gw))
    assert len(events) == 4 and all(e["round"] == 5 and e["type"] == "legit" for e in events)
