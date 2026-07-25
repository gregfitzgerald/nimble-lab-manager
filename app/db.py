"""SQLite connection + database bootstrap for Nimble Lab Manager.

The database is a single file (lab.db) built from schema.sql + seed.sql the first
time it is needed. Paths are derived from __file__ so the app stays portable.
"""

import os
import sqlite3

# Repo root = parent of the app/ package directory.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)

DB_PATH = os.path.join(ROOT_DIR, "lab.db")
SCHEMA_PATH = os.path.join(ROOT_DIR, "schema.sql")
SEED_PATH = os.path.join(ROOT_DIR, "seed.sql")


def get_conn():
    """Return a sqlite3 connection with Row rows and foreign keys enforced."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def init_db(force=False):
    """Build lab.db from schema.sql + seed.sql when it is missing.

    force=True deletes any existing database and rebuilds it from scratch
    (used by POST /api/reset).

    The demo login users (see app.auth.DEMO_USERS) are ensured on every call
    -- passwords are PBKDF2-hashed in Python, so they cannot live in seed.sql.
    The ensure step is idempotent, making repeated inits/resets safe.
    """
    from . import auth  # local import: auth imports get_conn from this module

    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    fresh = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if fresh:
            conn.executescript(_read(SCHEMA_PATH))
            if os.path.exists(SEED_PATH):
                conn.executescript(_read(SEED_PATH))
        auth.ensure_demo_users(conn)
        conn.commit()
    finally:
        conn.close()
    return DB_PATH


def rebuild_db():
    """Reset the demo data by dropping every table and re-running schema + seed
    IN PLACE, without deleting the database file.

    init_db(force=True) removes the file, which breaks persistence when lab.db
    lives on a bind-mounted / volume-backed path (the file's inode is what the
    mount tracks). This rebuild keeps the same file, so POST /api/reset survives
    a containerized deployment. Called only by the reset endpoint.
    """
    from . import auth  # local import: auth imports get_conn from this module

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
        if os.path.exists(SEED_PATH):
            conn.executescript(_read(SEED_PATH))
        auth.ensure_demo_users(conn)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    finally:
        conn.close()
    return DB_PATH
