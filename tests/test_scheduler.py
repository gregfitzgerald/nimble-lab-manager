"""Tests for the daily-digest scheduler's claim semantics.

The "already sent today" marker lives in app_setting (so it rides the database
volume) and is claimed with a single conditional upsert, so concurrent
workers/machines cannot both send. A failed send must release the claim so a
later tick retries.
"""

import app.notify as notify
import app.scheduler as sched


def test_claim_is_exclusive_per_day(db):
    assert sched._claim_today(db) is True
    # A second claim on the same day loses -- this is what stops duplicate sends
    # across workers/machines sharing one database.
    assert sched._claim_today(db) is False


def test_release_allows_reclaim(db):
    assert sched._claim_today(db) is True
    sched._release_claim(db)
    assert sched._claim_today(db) is True


def test_claim_marker_persists_in_app_setting(db):
    sched._claim_today(db)
    row = db.execute(
        "SELECT value FROM app_setting WHERE key = ?", (sched._MARKER_KEY,)
    ).fetchone()
    assert row is not None and row[0] == sched._now().date().isoformat()


def test_tick_releases_claim_when_send_fails(db, monkeypatch):
    """A tick that cannot deliver must not consume the day."""
    monkeypatch.setenv("NLM_DIGEST_HOUR", "0")  # always "time to send"
    monkeypatch.setattr(
        notify, "send_digest",
        lambda conn, **kw: {"sent": False, "reason": "smtp-not-configured",
                            "recipients": [], "total": 1, "urgent": 0},
    )
    sched._tick()  # the db fixture already points app.db.DB_PATH at this DB
    # claim released -> a later tick can still try
    assert sched._claim_today(db) is True


def test_tick_keeps_claim_after_successful_send(db, monkeypatch):
    monkeypatch.setenv("NLM_DIGEST_HOUR", "0")
    monkeypatch.setattr(
        notify, "send_digest",
        lambda conn, **kw: {"sent": True, "reason": "sent",
                            "recipients": ["a@b.com"], "total": 2, "urgent": 1},
    )
    sched._tick()
    # day consumed -> no duplicate send
    assert sched._claim_today(db) is False


def test_bad_timezone_falls_back(monkeypatch):
    monkeypatch.setenv("NLM_TZ", "Not/AZone")
    assert sched._now() is not None  # must not raise


def test_timezone_is_honoured(monkeypatch):
    monkeypatch.setenv("NLM_TZ", "UTC")
    assert sched._now().tzinfo is not None
