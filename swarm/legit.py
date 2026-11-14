"""Legit shopper (Graduate): python -m swarm.legit [--url URL]

Browses and orders through the gateway every SHOPPER_EVERY_S with the Bearer token, so the demo can show
real customers keep working while the red swarm is split. swarm.run starts one per round.
"""
import argparse
import threading

import httpx

from common.schema import GATEWAY_URL, H_AGENT, LEGIT_TOKEN, SHOPPER_EVERY_S, SHOPPER_ID

PAUSED = threading.Event()   # set while the hub round is paused; the swarm and shopper wait


def wait_if_paused(stop: threading.Event):
    while PAUSED.is_set() and not stop.is_set():
        stop.wait(0.1)


HEADERS = {H_AGENT: SHOPPER_ID, "Authorization": f"Bearer {LEGIT_TOKEN}"}
UNREACHABLE = 503   # reported when the gateway can't be reached, so it counts as legit_fail


def call(http: httpx.Client, emit, method: str, path: str, body=None):
    try:
        r = http.request(method, path, headers=HEADERS, json=body)
        status = r.status_code
        try:
            data = r.json()
        except ValueError:
            data = None
    except httpx.HTTPError as e:
        print(f"[shopper] {method} {path} failed: {e!r}")
        status, data = UNREACHABLE, None
    emit("legit", method=method, path=path, status=status)
    return status, data


def shop_once(http: httpx.Client, emit) -> bool:
    """List products, then order the first one listed. One `legit` event per request; True if both worked."""
    listed, data = call(http, emit, "GET", "/api/v1/products")
    items = data.get("items") if isinstance(data, dict) else None
    product = next((i["id"] for i in items or [] if isinstance(i, dict) and "id" in i), 1)
    ordered, _ = call(http, emit, "POST", "/api/v1/orders", {"product_id": product})
    return listed < 400 and ordered < 400


def run_shopper(round_id: int, url: str, emit, stop: threading.Event, every: float = SHOPPER_EVERY_S,
                transport: httpx.BaseTransport = None):
    """Shop every `every` seconds until stop is set. Events from after the round ended are dropped."""
    def round_emit(type_: str, **fields):
        if not stop.is_set():
            emit(type_, round_id, **fields)

    with httpx.Client(base_url=url, timeout=5.0, transport=transport) as http:
        while not stop.is_set():
            wait_if_paused(stop)
            shop_once(http, round_emit)
            stop.wait(every)


def main():
    from common import hub
    from swarm.run import print_emit

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=GATEWAY_URL, help=f"where to shop (default {GATEWAY_URL})")
    ap.add_argument("--local", action="store_true", help="print events instead of sending them to the hub")
    args = ap.parse_args()
    r = None if args.local else hub.get_round()
    try:
        run_shopper((r or {}).get("id", 0), args.url, print_emit if args.local else hub.emit, threading.Event())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
