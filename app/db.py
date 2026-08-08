"""SQLite connection + database bootstrap for Nimble Lab Manager.

The database is a single file (lab.db) built from schema.sql + seed.sql the first
time it is needed. Paths are derived from __file__ so the app stays portable.
"""

import logging
import os
import sqlite3

# Repo root = parent of the app/ package directory.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

DB_PATH = os.path.join(ROOT_DIR, "lab.db")
SCHEMA_PATH = os.path.join(ROOT_DIR, "schema.sql")
SEED_PATH = os.path.join(ROOT_DIR, "seed.sql")

log = logging.getLogger("nlm.db")


def get_conn():
    """Return a sqlite3 connection with Row rows and foreign keys enforced.

    WAL mode lets readers and writers proceed concurrently instead of blocking,
    and busy_timeout makes a briefly-locked write wait-and-retry rather than
    immediately erroring -- together they keep real multi-user load from
    surfacing as 'database is locked' 500s.
    """
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# Versioned migrations for an EXISTING database. schema.sql builds a fresh DB
# complete, so a new database is stamped at SCHEMA_VERSION and skips all of these;
# an older lab.db (created before a given change) has a lower PRAGMA user_version,
# so the runner applies every step above its version, in order, then stamps the
# new version. Each step is IF-NOT-EXISTS / idempotent, so a partially-upgraded
# DB (e.g. one that ran the previous ad-hoc index scripts) re-runs harmlessly.
#
# To add a schema change on a live deployment: add it to schema.sql (for fresh
# DBs) AND append a (version, sql) step here (for existing ones). Never edit or
# renumber a released step -- only append.
_MIGRATIONS = [
    (1, """
        CREATE INDEX IF NOT EXISTS idx_container_lot ON container(item_lot_id);
    """),
    (2, """
        -- Drop duplicate open broadcasts before the UNIQUE index can be built.
        DELETE FROM notification
         WHERE read_at IS NULL AND user_id IS NULL
           AND id NOT IN (SELECT MIN(id) FROM notification
                           WHERE read_at IS NULL AND user_id IS NULL
                           GROUP BY kind, entity_type, entity_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_unique_open
            ON notification(kind, entity_type, entity_id)
            WHERE read_at IS NULL AND user_id IS NULL;
    """),
]
SCHEMA_VERSION = _MIGRATIONS[-1][0] if _MIGRATIONS else 0


def _run_migrations(conn):
    """Apply every migration newer than the DB's recorded user_version, in order.

    A fresh database is stamped at SCHEMA_VERSION by init_db and so runs none of
    these; only a pre-existing DB at a lower version is upgraded.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, sql in _MIGRATIONS:
        if version <= current:
            continue
        try:
            conn.executescript(sql)
        except sqlite3.DatabaseError as exc:
            # A DB predating the referenced tables has nothing to migrate yet;
            # log it but keep going so a later applicable step still runs.
            log.warning("migration %d skipped: %s", version, exc)
        # PRAGMA user_version does not accept a bound parameter; version is an
        # int literal from this module, never user input.
        conn.execute(f"PRAGMA user_version = {int(version)}")
    conn.commit()


def init_db(force=False, seed_demo=None):
    """Build lab.db from schema.sql (+ optionally seed.sql) when it is missing.

    force=True deletes any existing database and rebuilds it from scratch.

    seed_demo controls whether the synthetic demo lab and the four well-known
    demo logins are loaded. When None it is read from the environment
    (NLM_SEED_DEMO, default off) so a deployed instance starts empty and secure:
    an admin account is bootstrapped instead (see app.auth.ensure_admin_bootstrap).
    The local launcher and dev tooling pass/set seed_demo on to keep the demo.
    Auth accounts are PBKDF2-hashed in Python, so they cannot live in seed.sql;
    the ensure/bootstrap step is idempotent, making repeated inits/resets safe.
    """
    from . import auth  # local import: auth imports get_conn from this module

    if seed_demo is None:
        seed_demo = auth.demo_enabled()

    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    fresh = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if fresh:
            conn.executescript(_read(SCHEMA_PATH))
            if seed_demo and os.path.exists(SEED_PATH):
                conn.executescript(_read(SEED_PATH))
            # schema.sql is already at the latest shape; stamp it so the
            # migration steps (which only bring OLD DBs forward) are skipped.
            conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        else:
            _run_migrations(conn)
        if seed_demo:
            auth.ensure_demo_users(conn)
        else:
            auth.ensure_admin_bootstrap(conn)
        conn.commit()
    finally:
        conn.close()
    return DB_PATH


def rebuild_db(seed_demo=None):
    """Reset the database by dropping every table and re-running schema (+ seed)
    IN PLACE, without deleting the database file.

    init_db(force=True) removes the file, which breaks persistence when lab.db
    lives on a bind-mounted / volume-backed path (the file's inode is what the
    mount tracks). This rebuild keeps the same file, so POST /api/reset survives
    a containerized deployment. Called only by the reset endpoint, which is
    itself limited to demo instances. seed_demo defaults to the environment.
    """
    from . import auth  # local import: auth imports get_conn from this module

    if seed_demo is None:
        seed_demo = auth.demo_enabled()

    conn = sqlite3.connect(DB_PATH)
    try:
        # Drop with FK enforcement off so table order does not matter; names
        # come from sqlite_master (never user input) and are quoted.
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (name,) in tables:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.executescript(_read(SCHEMA_PATH))
        if seed_demo and os.path.exists(SEED_PATH):
            conn.executescript(_read(SEED_PATH))
        # Freshly rebuilt from schema.sql -> already at the latest shape.
        conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        if seed_demo:
            auth.ensure_demo_users(conn)
        else:
            auth.ensure_admin_bootstrap(conn)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    finally:
        conn.close()
    return DB_PATH
