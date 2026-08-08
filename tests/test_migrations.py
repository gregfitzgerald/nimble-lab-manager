"""Versioned schema migrations (PRAGMA user_version).

A fresh DB is stamped at SCHEMA_VERSION and runs no migrations; an older DB is
brought forward step by step. This replaces the previous ad-hoc IF-NOT-EXISTS
scripts so a live deployment has a real upgrade path.
"""
import sqlite3

import app.db as appdb


def _uv(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _has_index(path, name):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
        ).fetchone() is not None
    finally:
        conn.close()


def test_fresh_db_is_stamped_at_schema_version(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    appdb.init_db(force=True, seed_demo=True)
    assert _uv(path) == appdb.SCHEMA_VERSION
    # the indexes the migrations add are present from schema.sql on a fresh DB
    assert _has_index(path, "idx_container_lot")
    assert _has_index(path, "idx_notification_unique_open")


def test_old_db_is_migrated_forward(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    appdb.init_db(force=True, seed_demo=True)

    # Simulate a database created before these migrations existed.
    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX idx_container_lot")
    conn.execute("DROP INDEX idx_notification_unique_open")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    appdb.init_db(seed_demo=True)  # non-fresh path -> runs migrations

    assert _uv(path) == appdb.SCHEMA_VERSION
    assert _has_index(path, "idx_container_lot")
    assert _has_index(path, "idx_notification_unique_open")


def test_migration_dedupes_before_unique_index(tmp_path, monkeypatch):
    """Migration 2 must clear duplicate open broadcasts, or the UNIQUE index
    build fails on a DB that accumulated them under the old (racy) code."""
    path = tmp_path / "dupes.db"
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    appdb.init_db(force=True, seed_demo=True)

    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX idx_notification_unique_open")
    conn.execute("PRAGMA user_version = 1")  # just before migration 2
    for _ in range(3):  # three identical open broadcasts
        conn.execute(
            """INSERT INTO notification
                   (created_at, user_id, kind, severity, message,
                    entity_type, entity_id, read_at)
               VALUES (datetime('now'), NULL, 'low_stock', 'warn', 'dup',
                       'inventory', 999, NULL)"""
        )
    conn.commit()
    conn.close()

    appdb.init_db(seed_demo=True)  # runs migration 2

    conn = sqlite3.connect(path)
    try:
        remaining = conn.execute(
            """SELECT COUNT(*) FROM notification
                WHERE entity_type='inventory' AND entity_id=999
                  AND read_at IS NULL"""
        ).fetchone()[0]
    finally:
        conn.close()
    assert remaining == 1, "duplicates were not collapsed before the unique index"
    assert _has_index(path, "idx_notification_unique_open")
