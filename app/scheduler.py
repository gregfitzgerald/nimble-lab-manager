"""Opt-in background scheduler for the daily alert digest.

A daemon thread wakes periodically and, once per day at or after a configured
hour, emails the alert digest (see app.notify). Entirely opt-in (NLM_SCHEDULER);
never runs during tests.

The "already sent today" marker lives in the app_setting table, not a sidecar
file, for two reasons: it rides the same volume as the database (a file beside
lab.db would sit on the container's ephemeral layer, since only lab.db itself is
symlinked onto the mount), and it lets the day be *claimed atomically*. Claiming
is a single conditional UPDATE, so with several workers -- or several machines --
sharing one database, exactly one of them sends. A failed send releases the claim
so the next tick retries.

Environment:
  NLM_SCHEDULER     "1" to enable the daily digest thread (default off)
  NLM_DIGEST_HOUR   hour (0-23) to send at, default 7
  NLM_TZ            IANA zone for that hour, e.g. "America/New_York". Defaults
                    to the server's local time -- which in a container is UTC,
                    so set this to get the lab's actual morning.

Note: on platforms that stop the machine when idle (e.g. Fly.io
auto_stop_machines with min_machines_running = 0), no thread runs while the
machine is asleep, so the digest cannot fire. Keep one machine running.
"""

import datetime
import logging
import os
import threading

from . import notify

log = logging.getLogger("nlm.scheduler")

_MARKER_KEY = "digest_last_sent"

_CHECK_INTERVAL_SEC = 900  # re-check every 15 minutes
_thread = None
_stop = None


def scheduler_enabled():
    return os.environ.get("NLM_SCHEDULER", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _digest_hour():
    try:
        return max(0, min(23, int(os.environ.get("NLM_DIGEST_HOUR", "7"))))
    except (TypeError, ValueError):
        return 7


def _now():
    """Current time in the configured zone (NLM_TZ), else server-local."""
    name = os.environ.get("NLM_TZ", "").strip()
    if name:
        try:
            from zoneinfo import ZoneInfo

            return datetime.datetime.now(ZoneInfo(name))
        except Exception:  # noqa: BLE001 -- bad/unknown zone must not stop the digest
            log.warning("NLM_TZ=%r is not a usable time zone; using server time", name)
    return datetime.datetime.now()


def _claim_today(conn):
    """Atomically claim today's digest. True only for the caller that wins.

    A single conditional upsert: the row is written only when it does not
    already hold today's date, so concurrent workers/machines cannot both send.
    """
    today = _now().date().isoformat()
    cur = conn.execute(
        """INSERT INTO app_setting (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value
            WHERE app_setting.value IS NOT excluded.value""",
        (_MARKER_KEY, today),
    )
    conn.commit()
    return cur.rowcount > 0


def _release_claim(conn):
    """Undo a claim so a failed send is retried on the next tick."""
    conn.execute("DELETE FROM app_setting WHERE key = ?", (_MARKER_KEY,))
    conn.commit()


def _tick():
    """One scheduler check: send the digest if it is time and not already sent."""
    if _now().hour < _digest_hour():
        return
    from .db import get_conn

    conn = get_conn()
    try:
        # Claim first, then send: whoever wins the claim owns today's send.
        if not _claim_today(conn):
            return
        try:
            result = notify.send_digest(conn)
        except Exception:
            _release_claim(conn)
            raise
        # A send failure (or a missing/unconfigured mailer) should not consume
        # the day -- release so a later tick, or fixed config, still delivers.
        if not (result.get("sent") or result.get("reason") == "no-open-alerts"):
            _release_claim(conn)
            log.warning("digest not sent (%s); will retry", result.get("reason"))
        elif result.get("sent"):
            log.info("daily digest sent to %s", result.get("recipients"))
    finally:
        conn.close()


def _run(stop_event):
    while not stop_event.wait(_CHECK_INTERVAL_SEC):
        try:
            _tick()
        except Exception:  # noqa: BLE001 -- a bad tick must not kill the thread
            log.exception("digest scheduler tick failed")


def start():
    """Start the daily-digest thread if enabled. Idempotent."""
    global _thread, _stop
    if not scheduler_enabled() or _thread is not None:
        return
    if not (notify.smtp_configured() and notify.digest_recipients()):
        log.warning(
            "NLM_SCHEDULER is on but SMTP/NLM_DIGEST_TO is not configured; "
            "the daily digest will not be sent until both are set."
        )
    _stop = threading.Event()
    _thread = threading.Thread(target=_run, args=(_stop,), name="nlm-digest", daemon=True)
    _thread.start()
    log.info("digest scheduler started (send hour=%d)", _digest_hour())


def stop():
    """Signal the thread to exit. Idempotent."""
    global _thread, _stop
    if _stop is not None:
        _stop.set()
    _thread = None
    _stop = None
