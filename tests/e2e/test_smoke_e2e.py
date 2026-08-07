"""Playwright end-to-end smoke suite for Nimble Lab Manager.

What this proves: the buildless SPA in web/ boots, and every view hash renders
against the real FastAPI backend without throwing a console error, a page error,
or the app's "Could not render this view" fallback.

Design notes
------------
Server: app.db derives every connection from the module-global app.db.DB_PATH,
read at call time by get_conn()/init_db(). There is no environment override for
the DB path, so a plain `uvicorn` subprocess would always hit the repo's dev
lab.db. Instead we start the app IN-PROCESS on a background thread after
pointing app.db.DB_PATH at a fresh temp file and seeding it -- the app's lifespan
init_db() then no-ops on the copy. NLM_AUTH=off (read per-call by app.auth) makes
every request act as a synthetic admin, so the SPA boots straight past the login
gate and can reach every view.

Graceful skip: if playwright (or its chromium browser) is unavailable, the whole
module skips so the normal `pytest -q` run is never broken on a browserless host.
"""

import contextlib
import os
import shutil
import socket
import threading
import time

import pytest

# --- graceful skip when playwright / chromium is unavailable ---------------- #
pytest.importorskip("playwright", reason="playwright not installed")
from playwright.sync_api import sync_playwright  # noqa: E402


VIEWS = [
    "dashboard", "inventory", "catalog", "kits", "stocktake", "tickets", "map",
    "equipment", "purchasing", "funds", "controlled", "safety", "labels",
    "analytics", "reports", "usage", "people", "history", "game", "help",
]


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


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """Start the real app on an ephemeral port with a fresh temp DB.

    Yields the base URL. Runs in-process on a daemon uvicorn thread so the temp
    DB path (a module global) is honoured without an env hook.
    """
    import uvicorn

    import app.db as appdb

    # Point the app at an isolated temp DB before anything opens a connection.
    db_file = tmp_path_factory.mktemp("nlm-e2e") / "lab.db"
    original_db = appdb.DB_PATH
    appdb.DB_PATH = str(db_file)
    os.environ["NLM_AUTH"] = "off"  # synthetic admin: SPA boots past login

    appdb.init_db(force=True, seed_demo=True)  # seed schema + demo data into the temp DB

    # Import after DB_PATH is set so the lifespan init_db() targets the temp DB.
    from app.server import app

    host, port = "127.0.0.1", _free_port()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        if not _wait_for_port(host, port):
            pytest.fail(f"e2e server never came up on {host}:{port}")
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        appdb.DB_PATH = original_db
        with contextlib.suppress(Exception):
            shutil.rmtree(db_file.parent, ignore_errors=True)


@pytest.fixture(scope="session")
def browser():
    """Launch headless chromium; skip the suite if the browser is missing."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # browser binary not installed / no deps
            pytest.skip(f"chromium unavailable: {exc}")
        try:
            yield browser
        finally:
            browser.close()


def _new_page(browser):
    """A page wired to record console errors and uncaught page errors."""
    page = browser.new_page()
    errors = []
    page.on(
        "console",
        lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
    return page, errors


def test_every_view_renders_without_errors(live_server, browser):
    page, errors = _new_page(browser)
    try:
        page.goto(live_server, wait_until="networkidle")
        # Wait for the SPA to resolve /api/me and paint the nav (auth=off).
        page.wait_for_selector("#nav .nav-item", timeout=15000)

        failures = []
        for view in VIEWS:
            del errors[:]  # only count errors raised while on this view
            page.evaluate("(v) => { location.hash = '#' + v; }", view)
            # Give the async view render a beat to run and settle.
            page.wait_for_timeout(400)

            body = page.inner_text("body")
            root_text = page.eval_on_selector(
                "#view-root", "el => el.textContent.trim()"
            )
            if "Could not render this view" in body:
                failures.append(f"{view}: 'Could not render this view' fallback")
            if not root_text:
                failures.append(f"{view}: #view-root is empty")
            if errors:
                failures.append(f"{view}: {errors[:3]}")

        assert not failures, "View smoke failures:\n" + "\n".join(failures)
    finally:
        page.close()


def test_inventory_item_detail_opens(live_server, browser):
    """Interaction flow: clicking an inventory row opens the product modal, and
    its 'Open full record' action swaps in the detail view ('Back to inventory')."""
    page, errors = _new_page(browser)
    try:
        page.goto(live_server, wait_until="networkidle")
        page.wait_for_selector("#nav .nav-item", timeout=15000)
        page.evaluate("() => { location.hash = '#inventory'; }")
        page.wait_for_selector("#view-root tr.row-link", timeout=15000)
        page.query_selector("#view-root tr.row-link").click()

        # A row click opens the shared product modal.
        page.wait_for_selector(".modal-card", timeout=15000)

        # "Open full record" closes the modal and swaps in the detail view.
        page.evaluate(
            "() => { for (const b of document.querySelectorAll('.modal-card button')) "
            "{ if (/Open full record/.test(b.textContent)) { b.click(); return; } } }"
        )
        page.wait_for_function(
            "() => document.querySelector('#view-root') "
            "&& /Back to inventory/.test(document.querySelector('#view-root').textContent)",
            timeout=15000,
        )
        assert not errors, f"errors during detail flow: {errors[:3]}"
    finally:
        page.close()
