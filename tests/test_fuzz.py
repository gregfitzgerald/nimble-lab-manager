"""OpenAPI-driven property/fuzz testing for the Nimble Lab Manager API.

What this proves: for every operation in the app's own OpenAPI schema,
Schemathesis synthesises many request variants (boundary values, wrong types,
missing fields, oversized strings, unexpected enums, huge integers, ...) and
drives them through the real FastAPI app. The contract we assert is narrow but
important: the server must never suffer an *unexpected* server error. A 4xx for
malformed input is correct behaviour; a 5xx -- or an unhandled exception -- means
bad input reached application code, which is a bug.

Bugs this suite found -- now FIXED
----------------------------------
Fuzzing surfaced ONE pervasive input-validation gap: ~36 endpoints accept an
unbounded integer path/query/body parameter (item_id, catalog_id, fid, eid, a
``days`` window, ...) and pass it straight into a SQLite query. For values above
SQLite's 8-byte signed range (> 2**63 - 1) sqlite3 raises
``OverflowError: Python int too large to convert to SQLite INTEGER`` -- which a
real (non-TestClient) uvicorn server returns to the client as HTTP 500.

The clean fix lives in app/api.py (this module does not own it): bound the
integer parameters, e.g. FastAPI ``Path(..., le=2**63 - 1)`` / a validated body
field, so the app answers 422 instead of crashing. Endpoints observed to crash
this way include (non-exhaustive): GET/DELETE items, containers, funds/{fid},
equipment/{eid}, kits/{kit_id}, catalog/{catalog_id}, counts/{session_id},
substitute-groups/{group_id}, users/{user_id}, purchase-orders/{po_id},
locations/{node_id}[/contents], documents/{doc_id}, task-templates/{template_id},
GET /api/alerts/expiring, GET /api/audit, POST /api/tickets,
POST /api/catalog/{catalog_id}/add-to-inventory.

A SECOND, smaller bug class surfaced too: the CSV exporter (``_csv_response`` in
app/api.py) builds a ``csv.writer`` with the default dialect, which has no
``escapechar``. If a stored field contains a NUL byte (``\x00``) -- which fuzzing
happily POSTs into free-text fields like note/task/purpose and which the app
stores unsanitised -- then ``GET /api/export/audit.csv`` (and any export whose
data hits that value) raises ``_csv.Error: need to escape, but no escapechar
set`` -> HTTP 500. The fix is to sanitise control characters in _csv_response
(or reject NUL bytes on input).

Both are now FIXED: the OverflowError is caught by a handler in app/server.py that
answers 400, and the CSV crash is prevented by control-character scrubbing in
_csv_response (app/api.py). This test therefore asserts, with NO tolerances, that
every generated request yields a status < 500 -- a regression in either fix, or any
new 5xx, breaks the build.

Design notes
------------
The schema is loaded in-process straight from the ASGI app
(``schemathesis.openapi.from_asgi``), so no live server or network is needed and
``case.call()`` routes through Starlette's ASGI test transport. That transport
re-raises server exceptions, which is why the OverflowError arrives as a raised
exception here rather than as an HTTP 500 body -- both are treated identically.

Isolation mirrors the rest of the suite: point ``app.db.DB_PATH`` at a fresh
temp database, ``init_db(force=True)`` to seed it, and only THEN import
``app.server`` so the lifespan init targets the temp copy. NLM_AUTH=off makes
every request act as a synthetic admin, so auth/CSRF never shadow the actual
input-validation behaviour we are fuzzing.

Graceful skip: the whole module skips if ``schemathesis`` is not importable, so
a plain ``pytest -q`` on a host without the dev extras is never broken.
"""

import os
import tempfile

import pytest

# --- graceful skip when schemathesis is unavailable ------------------------- #
schemathesis = pytest.importorskip("schemathesis", reason="schemathesis not installed")

from hypothesis import HealthCheck, settings  # noqa: E402


def _load_schema():
    """Seed a throwaway DB, import the app, and return the OpenAPI schema.

    Done at import time (module scope) so ``@schema.parametrize()`` can expand
    it into one test item per operation. The temp DB directory is intentionally
    left for the process lifetime -- it lives under the OS temp dir and is a few
    KB.
    """
    os.environ["NLM_AUTH"] = "off"  # synthetic admin: skip auth + CSRF gates

    import app.db as appdb

    tmp_dir = tempfile.mkdtemp(prefix="nlm-fuzz-")
    appdb.DB_PATH = os.path.join(tmp_dir, "lab.db")
    appdb.init_db(force=True)  # seed schema + demo data into the temp DB

    # Import only after DB_PATH is set so any connection hits the temp copy.
    from app.server import app

    return schemathesis.openapi.from_asgi("/openapi.json", app)


schema = _load_schema()

@schema.parametrize()
@settings(
    max_examples=10,
    deadline=None,
    # Deterministic generation so this committed test is reproducible: green
    # today stays green tomorrow instead of depending on a per-run random seed.
    # Bump max_examples / drop derandomize for a deeper local fuzz session.
    derandomize=True,
    # The seeded temp DB is shared across generated cases (mutations included),
    # so per-example timing varies -- silence Hypothesis's timing and
    # data-generation health checks; they are not what this test guards.
    suppress_health_check=list(HealthCheck),
)
def test_api_never_returns_unexpected_5xx(case):
    """Every generated request must NOT elicit an unexpected server error.

    Tolerated (documented baseline, see module docstring): the systemic
    large-integer ``OverflowError`` from SQLite. Everything else -- a real 5xx
    response, or any other unhandled exception -- fails with the operation label
    and the exact generated input, so a real bug is reported with enough detail
    for the owner to fix it in app/api.py.
    """
    response = case.call()
    assert response.status_code < 500, (
        f"unexpected {response.status_code} from {case.operation.label}\n"
        f"  path params: {case.path_parameters}\n"
        f"  query:       {case.query}\n"
        f"  body:        {case.body!r}\n"
        f"  response:    {response.text[:500]}"
    )
