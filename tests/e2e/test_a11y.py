"""Accessibility (axe-core) audit for the Nimble Lab Manager SPA.

What this proves: a handful of key views (dashboard, inventory, purchasing,
funds, help) render markup that passes axe-core with zero CRITICAL or SERIOUS
violations. Minor/moderate findings are allowed but counted and printed, so the
run establishes an a11y baseline the team can watch for regressions.

Design notes
------------
Server + browser handling mirrors tests/e2e/test_smoke_e2e.py: the app runs
in-process on a daemon thread against a fresh temp DB (app.db.DB_PATH is a
module global read at call time, so this is the only way to isolate it), with
NLM_AUTH=off so the SPA boots past the login gate straight to every view. The
fixtures are duplicated here (rather than imported) to keep this module a
self-contained, independently skippable audit.

Graceful skip: the module skips if playwright, axe-playwright-python, or the
chromium browser/its system deps are unavailable, so a plain ``pytest -q`` on a
browserless host is never broken.
"""

import contextlib
import os
import shutil
import socket
import threading
import time

import pytest

# --- graceful skip when playwright / axe is unavailable --------------------- #
pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip(
    "axe_playwright_python", reason="axe-playwright-python not installed"
)
from axe_playwright_python.sync_playwright import Axe  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


# Key views to audit -- one representative from each major area of the app.
A11Y_VIEWS = ["dashboard", "inventory", "purchasing", "funds", "help"]

# axe impact levels we treat as failures (WCAG-blocking). minor/moderate are
# collected and printed but do not fail the build.
BLOCKING_IMPACTS = {"critical", "serious"}


def _free_port():
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
    """Start the real app on an ephemeral port with a fresh temp DB."""
    import uvicorn

    import app.db as appdb

    db_file = tmp_path_factory.mktemp("nlm-a11y") / "lab.db"
    original_db = appdb.DB_PATH
    appdb.DB_PATH = str(db_file)
    os.environ["NLM_AUTH"] = "off"  # synthetic admin: SPA boots past login

    appdb.init_db(force=True)  # seed schema + demo data into the temp DB

    from app.server import app

    host, port = "127.0.0.1", _free_port()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        if not _wait_for_port(host, port):
            pytest.fail(f"a11y server never came up on {host}:{port}")
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        appdb.DB_PATH = original_db
        with contextlib.suppress(Exception):
            shutil.rmtree(db_file.parent, ignore_errors=True)


# Module scope (not session): tests/e2e/test_smoke_e2e.py also opens a
# session-scoped sync_playwright browser. Playwright's sync API cannot be nested
# in one thread, so a session-scoped browser here would stay open across the
# smoke module and make its own sync_playwright() raise "Sync API inside the
# asyncio loop". Module scope closes this browser when the a11y module finishes,
# before the smoke module starts, so the two never overlap.
@pytest.fixture(scope="module")
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


def _audit_view(page, base_url, view):
    """Navigate to a view, run axe-core, and return its violation list.

    Each view fetches its data and renders asynchronously; a slow browser can
    otherwise let axe scan a half-built DOM (which silently reports "clean"
    because the widgets under audit are not there yet). We therefore wait for
    the network to go idle AND for #view-root to hold a substantial amount of
    rendered content before auditing, so the baseline reflects the real UI.
    """
    page.evaluate("(v) => { location.hash = '#' + v; }", view)
    page.wait_for_selector("#view-root", timeout=15000)
    # Wait for the view's async data fetch + render to actually finish.
    page.wait_for_load_state("networkidle")
    page.wait_for_function(
        "() => { const r = document.querySelector('#view-root');"
        " return r && r.textContent.trim().length > 40; }",
        timeout=15000,
    )
    page.wait_for_timeout(600)

    results = Axe().run(page)
    return results.response["violations"]


def test_key_views_have_no_critical_or_serious_a11y_violations(live_server, browser):
    page = browser.new_page()
    try:
        page.goto(live_server, wait_until="networkidle")
        page.wait_for_selector("#nav .nav-item", timeout=15000)

        # impact -> total node count, aggregated across all audited views.
        totals = {}
        blocking = []  # (view, id, impact, node_count) for critical/serious
        per_view_report = []

        for view in A11Y_VIEWS:
            violations = _audit_view(page, live_server, view)
            view_counts = {}
            for v in violations:
                impact = v.get("impact") or "unknown"
                nodes = len(v.get("nodes", []))
                totals[impact] = totals.get(impact, 0) + nodes
                view_counts[impact] = view_counts.get(impact, 0) + nodes
                if impact in BLOCKING_IMPACTS:
                    blocking.append((view, v.get("id"), impact, nodes))
            per_view_report.append(
                f"  {view:<11} " + (
                    ", ".join(f"{k}={view_counts[k]}" for k in sorted(view_counts))
                    or "clean"
                )
            )

        # Baseline report: printed with `pytest -s` and always on failure.
        print("\n=== axe-core a11y baseline (violation node counts) ===")
        print("\n".join(per_view_report))
        print(
            "  TOTALS     "
            + (", ".join(f"{k}={totals[k]}" for k in sorted(totals)) or "clean")
        )

        assert not blocking, (
            "critical/serious axe-core violations found:\n"
            + "\n".join(
                f"  [{impact}] {vid} on '{view}' ({nodes} node(s))"
                for view, vid, impact, nodes in blocking
            )
        )
    finally:
        page.close()
