"""Concurrency / load proof: the atomic guarded stock update never oversells.

What this proves: under REAL parallel HTTP load (many simultaneous requests
against a live server on a socket, not an in-process TestClient simulation), the
conditional
    UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?
    WHERE item_id = ? AND quantity_on_hand >= ?
in app.api is the single gate that decides a consume. SQLite serialises writers
and each re-evaluates its WHERE against committed state, so of N concurrent
consumers of q units against a stock of S (with N*q > S) exactly floor(S/q) can
succeed. Stock lands at S - floor(S/q)*q and never goes negative; the losers get
a clean 400, never a 5xx.

Design mirrors tests/e2e/test_smoke_e2e.py's live_server fixture: the app is
started IN-PROCESS on a daemon uvicorn thread after app.db.DB_PATH is pointed at
a fresh temp file (the DB path is a module global with no env hook), with
NLM_AUTH=off so requests act as a synthetic admin and no CSRF/auth blocks the
load. FastAPI runs sync endpoints in a threadpool, so the ThreadPoolExecutor
below drives genuinely concurrent writers. The module skips gracefully if the
server can't bind/start so a normal ``pytest -q`` run is never broken.
"""

import contextlib
import json
import math
import os
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

# --- graceful skip when uvicorn is unavailable ------------------------------ #
pytest.importorskip("uvicorn", reason="uvicorn not installed")


def _free_port():
    """Grab an OS-assigned free TCP port, then release it for the server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(host, port, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.closing(socket.socket()) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start the real app on an ephemeral port with a fresh temp DB.

    Yields the base URL. Runs in-process on a daemon uvicorn thread so the temp
    DB path (a module global) is honoured without an env hook. Skips gracefully
    if uvicorn cannot start or the port never comes up.
    """
    import uvicorn

    import app.db as appdb

    # Point the app at an isolated temp DB before anything opens a connection.
    db_file = tmp_path_factory.mktemp("nlm-concurrency") / "lab.db"
    original_db = appdb.DB_PATH
    appdb.DB_PATH = str(db_file)
    os.environ["NLM_AUTH"] = "off"  # synthetic admin: no auth/CSRF gate

    appdb.init_db(force=True)  # seed schema + demo data into the temp DB

    # Import after DB_PATH is set so the lifespan init_db() targets the temp DB.
    from app.server import app

    host, port = "127.0.0.1", _free_port()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        if not _wait_for_port(host, port):
            pytest.skip(f"concurrency server never came up on {host}:{port}")
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        appdb.DB_PATH = original_db
        with contextlib.suppress(Exception):
            shutil.rmtree(db_file.parent, ignore_errors=True)


# --- tiny stdlib HTTP helpers (no third-party deps) ------------------------- #

def _request(method, url, payload=None, timeout=30):
    """Perform an HTTP request, returning (status_code, parsed_json_or_None).

    A 4xx is a normal outcome here (an insufficient-stock 400), so HTTPError is
    caught and its status returned rather than raised.
    """
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8") or "null"
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "null"
        with contextlib.suppress(Exception):
            return exc.code, json.loads(raw)
        return exc.code, None


def _get_qty(base, item_id):
    status, body = _request("GET", f"{base}/api/items/{item_id}")
    assert status == 200, f"GET item {item_id} -> {status}"
    # /api/items/{id} nests the inventory row under "item".
    return body["item"]["quantity_on_hand"]


def _set_stock_to(base, item_id, target):
    """Drive quantity_on_hand to exactly ``target`` via restock/consume."""
    current = _get_qty(base, item_id)
    delta = target - current
    if delta > 0:
        status, _ = _request(
            "POST", f"{base}/api/items/{item_id}/restock", {"quantity": delta}
        )
        assert status == 200, f"restock -> {status}"
    elif delta < 0:
        status, _ = _request(
            "POST", f"{base}/api/items/{item_id}/consume", {"quantity": -delta}
        )
        assert status == 200, f"consume-to-target -> {status}"
    assert _get_qty(base, item_id) == target
    return target


def _pick_item(base):
    status, items = _request("GET", f"{base}/api/items")
    assert status == 200 and items, "no items available to test against"
    return items[0]["item_id"]


def _fire_concurrent(fn, n):
    """Run callable ``fn`` n times concurrently; return list of status codes."""
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(fn) for _ in range(n)]
        return [f.result() for f in futures]


# --- Scenario 1: parallel POST /consume race -------------------------------- #

def test_concurrent_consume_never_oversells(live_server):
    base = live_server
    item_id = _pick_item(base)
    S, q, N = 20, 3, 30  # N*q = 90 >> S = 20
    _set_stock_to(base, item_id, S)

    expected_success = S // q  # floor(20/3) = 6

    def consume():
        status, _ = _request(
            "POST", f"{base}/api/items/{item_id}/consume", {"quantity": q}
        )
        return status

    codes = _fire_concurrent(consume, N)

    ok = sum(c == 200 for c in codes)
    bad = sum(c == 400 for c in codes)
    server_errors = [c for c in codes if 500 <= c < 600]
    final = _get_qty(base, item_id)

    assert not server_errors, f"5xx responses under load: {server_errors}"
    assert ok == expected_success, (
        f"expected {expected_success} successes, got {ok} (codes={sorted(codes)})"
    )
    assert bad == N - expected_success, (
        f"expected {N - expected_success} rejections, got {bad}"
    )
    assert final == S - expected_success * q, (
        f"final stock {final} != {S - expected_success * q}"
    )
    assert final >= 0, f"stock went negative: {final}"

    print(
        f"\n[consume race] S={S} q={q} N={N}: {ok} x 200 / {bad} x 400, "
        f"final on-hand={final}, no 5xx, never negative"
    )


# --- Scenario 2: parallel POST /tickets race (tickets also consume) --------- #

def test_concurrent_tickets_never_oversell(live_server):
    base = live_server
    item_id = _pick_item(base)
    S, q, N = 21, 4, 24  # N*q = 96 >> S = 21; floor(21/4) = 5
    _set_stock_to(base, item_id, S)

    expected_success = S // q

    def create_ticket():
        status, _ = _request(
            "POST",
            f"{base}/api/tickets",
            {
                "task": "concurrency-probe",
                "consume": True,
                "lines": [{"item_id": item_id, "quantity": q}],
            },
        )
        return status

    codes = _fire_concurrent(create_ticket, N)

    ok = sum(c == 200 for c in codes)
    bad = sum(c == 400 for c in codes)
    server_errors = [c for c in codes if 500 <= c < 600]
    final = _get_qty(base, item_id)

    assert not server_errors, f"5xx responses under load: {server_errors}"
    assert ok == expected_success, (
        f"expected {expected_success} successes, got {ok} (codes={sorted(codes)})"
    )
    assert bad == N - expected_success, (
        f"expected {N - expected_success} rejections, got {bad}"
    )
    assert final == S - expected_success * q, (
        f"final stock {final} != {S - expected_success * q}"
    )
    assert final >= 0, f"stock went negative: {final}"
    # invariant restated: leftover is the remainder S mod q
    assert final == S - math.floor(S / q) * q

    print(
        f"\n[ticket race] S={S} q={q} N={N}: {ok} x 200 / {bad} x 400, "
        f"final on-hand={final}, no 5xx, never negative"
    )
