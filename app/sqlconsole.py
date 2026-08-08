"""Read-only SQL console over the lab database.

The backend is a single SQLite file, so letting an admin ask it a question
directly is genuinely useful -- "how much did we spend on antibodies per month
per fund" is one query away and no report can anticipate every question. But an
open SQL box is also the most dangerous surface in the app, so this module is
built defensively and is OFF unless an admin explicitly turns it on.

Four independent layers, so no single mistake is fatal:

1. Feature gate      -- disabled unless ui_config.sql_console_enabled is true,
                        and the endpoint is admin-only regardless.
2. Read-only handle  -- the connection is opened with mode=ro, so the database
                        cannot be written even if everything below is fooled.
3. Authorizer        -- SQLite itself vetoes any action that is not a plain read:
                        no INSERT/UPDATE/DELETE/DDL, no ATTACH (which would let a
                        query read or write other files), no PRAGMA, no
                        load_extension. This works at the parse level, so it
                        cannot be evaded by clever SQL the way a regex can.
4. Secret redaction  -- reads of password hashes/salts and live session tokens are
                        refused outright. An admin already has full data access,
                        but handing out session tokens would let them silently
                        take over another user's session, and hashes are worth
                        stealing offline.

Plus limits: one statement only, a hard row cap, and a wall-clock deadline
enforced by a progress handler so a cartesian join cannot pin the CPU.
"""

import re
import sqlite3
import time

# Reads that are refused even though the caller is an admin. (table, column).
_BLOCKED_COLUMNS = {
    ("app_user", "password_hash"),
    ("app_user", "password_salt"),
    ("session", "token"),
}
# Whole tables that only ever hold live credentials.
_BLOCKED_TABLES = {"session"}

# SQLite actions that constitute reading. Everything else is denied.
_READ_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}
_DANGEROUS_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}

MAX_ROWS = 1000
TIMEOUT_SECONDS = 5.0
# A thousand rows can still be enormous if a column holds a large blob or a
# generated string, so cap the total payload as well as the row count.
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_CELL_CHARS = 4000


class QueryError(Exception):
    """A query the console refuses to run, or that failed. Message is user-facing."""


def _authorizer(action, arg1, arg2, db_name, trigger):
    """Veto anything that is not a plain read of a non-secret column."""
    if action == sqlite3.SQLITE_FUNCTION:
        # arg2 carries the function name for SQLITE_FUNCTION.
        if (arg2 or "").lower() in _DANGEROUS_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        table = (arg1 or "").lower()
        column = (arg2 or "").lower()
        if table in _BLOCKED_TABLES:
            return sqlite3.SQLITE_DENY
        if (table, column) in _BLOCKED_COLUMNS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action in _READ_ACTIONS:
        return sqlite3.SQLITE_OK
    # Everything else -- writes, DDL, ATTACH, PRAGMA, transactions -- is refused.
    return sqlite3.SQLITE_DENY


def _single_statement(sql):
    """Reject anything that is not exactly one statement.

    Guards against a trailing second statement riding along. The authorizer would
    veto a write anyway; this keeps the error message honest and the semantics
    predictable.
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise QueryError("Enter a query.")
    if not sqlite3.complete_statement(stripped + ";"):
        raise QueryError("That does not look like a complete SQL statement.")
    # A ';' left inside (outside of a string literal) means more than one statement.
    without_strings = re.sub(r"'[^']*'|\"[^\"]*\"", "", stripped)
    if ";" in without_strings:
        raise QueryError("Only one statement can be run at a time.")
    return stripped


def run_query(db_path, sql, max_rows=MAX_ROWS, timeout=TIMEOUT_SECONDS):
    """Execute a read-only query. Returns {columns, rows, row_count, truncated,
    elapsed_ms}. Raises QueryError with a user-facing message on refusal/failure."""
    statement = _single_statement(sql)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=timeout)
    except sqlite3.Error as exc:
        raise QueryError(f"Could not open the database read-only: {exc}") from exc

    started = time.monotonic()
    deadline = started + timeout
    try:
        # Abort long-running queries: the handler runs every N VM steps and a
        # truthy return aborts. This is what stops a cartesian join from pinning
        # the CPU for minutes.
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
        conn.set_authorizer(_authorizer)
        cur = conn.execute(statement)
        if cur.description is None:
            raise QueryError("That statement returned no result set.")
        columns = [d[0] for d in cur.description]
        # Stream row by row rather than fetchmany(max_rows + 1): a query like
        # SELECT zeroblob(...) or a big group_concat can make a single row huge,
        # so stop on a byte budget as well as a row count.
        rows = []
        budget = MAX_RESULT_BYTES
        truncated = False
        while len(rows) < max_rows:
            row = cur.fetchone()
            if row is None:
                break
            safe = _safe_row(row)
            rows.append(safe)
            budget -= sum(len(str(v)) for v in safe if v is not None)
            if budget <= 0:
                truncated = True
                break
        else:
            truncated = cur.fetchone() is not None
    except sqlite3.DatabaseError as exc:
        # Authorizer denials surface as a bare "not authorized" DatabaseError and
        # timeouts as "interrupted"; translate both into something a human can act
        # on, since these are the two a user will actually hit.
        msg = str(exc)
        lowered = msg.lower()
        if "interrupted" in lowered:
            raise QueryError(
                f"Query took longer than {timeout:g}s and was stopped. "
                "Add a WHERE clause or a LIMIT."
            ) from exc
        if (
            "not authorized" in lowered
            or "prohibited" in lowered
            or "authorization denied" in lowered
        ):
            raise QueryError(
                "Not allowed. This console is read-only: it cannot change data or "
                "the schema, and cannot read passwords or session tokens. Only "
                "SELECT queries over lab data are permitted."
            ) from exc
        if "readonly" in lowered or "read-only" in lowered:
            raise QueryError(
                "Not allowed: the database is open read-only, so nothing can be "
                "written from here."
            ) from exc
        raise QueryError(f"SQL error: {msg}") from exc
    except sqlite3.Warning as exc:
        # sqlite3.Warning is NOT a DatabaseError subclass, so without this it
        # escaped as an unhandled 500 (and the attempt went unaudited).
        raise QueryError(f"SQL error: {exc}") from exc
    except (ValueError, TypeError, OverflowError) as exc:
        # Value coercion failures (e.g. an out-of-range number) are bad input,
        # not a server fault.
        raise QueryError(f"Could not return that result: {exc}") from exc
    finally:
        try:
            conn.set_authorizer(None)
        except sqlite3.Error:
            pass
        conn.close()

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def _safe_row(row):
    """Coerce a row to JSON-safe values.

    Blobs become a short placeholder, over-long strings are clipped, and
    non-finite floats (SELECT 1e400) become text -- json.dumps emits bare
    Infinity/NaN for those, which is invalid JSON and made the response
    unparseable to the client.
    """
    out = []
    for value in row:
        if isinstance(value, (bytes, bytearray, memoryview)):
            out.append(f"<{len(bytes(value))} bytes>")
        elif isinstance(value, float) and (value != value or value in (
            float("inf"), float("-inf")
        )):
            out.append(str(value))
        elif isinstance(value, str) and len(value) > MAX_CELL_CHARS:
            out.append(value[:MAX_CELL_CHARS] + f"... (+{len(value) - MAX_CELL_CHARS} chars)")
        else:
            out.append(value)
    return out


def schema_overview(db_path):
    """Table and column names, so the console can show what is queryable.

    Secret columns are omitted from the listing as well as from results, so the
    console never advertises something it will refuse to return.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        tables = []
        for row in conn.execute(
            """SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name"""
        ).fetchall():
            name = row["name"]
            if name.lower() in _BLOCKED_TABLES:
                continue
            cols = [
                c["name"] for c in conn.execute(f'PRAGMA table_info("{name}")')
                if (name.lower(), c["name"].lower()) not in _BLOCKED_COLUMNS
            ]
            tables.append({"name": name, "columns": cols})
        return tables
    finally:
        conn.close()
