"""Opt-in background scheduler for the daily alert digest.

A single daemon thread wakes periodically and, once per day at or after a
configured hour, emails the alert digest (see app.notify). It is entirely
opt-in (NLM_SCHEDULER) and never runs during tests. The "sent today" marker is
persisted next to the database file so a restart does not re-send.

Environment:
  NLM_SCHEDULER     "1" to enable the daily digest thread (default off)
  NLM_DIGEST_HOUR   local hour (0-23) to send at, default 7

Note: on platforms that stop the machine when idle (e.g. Fly.io
auto_stop_machines), a background thread cannot run while the machine is asleep;
keep at least one machine running for scheduled digests.
"""

import datetime
import logging
import os
import threading

from . import notify

log = logging.getLogger("nlm.scheduler")

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


def _marker_path():
    from .db import DB_PATH

    return DB_PATH + ".digest"


def _sent_today():
    try:
        with open(_marker_path(), encoding="utf-8") as fh:
            return fh.read().strip() == datetime.date.today().isoformat()
    except OSError:
        return False


def _mark_sent_today():
    try:
        with open(_marker_path(), "w", encoding="utf-8") as fh:
            fh.write(datetime.date.today().isoformat())
    except OSError as exc:
        log.warning("could not write digest marker: %s", exc)


def _tick():
    """One scheduler check: send the digest if it is time and not already sent."""
    if datetime.datetime.now().hour < _digest_hour() or _sent_today():
        return
    from .db import get_conn

    conn = get_conn()
    try:
        result = notify.send_digest(conn)
    finally:
        conn.close()
    # Mark the day done if we sent, or if there was simply nothing to report --
    # either way today's digest decision is made and should not repeat.
    if result.get("sent") or result.get("reason") == "no-open-alerts":
        _mark_sent_today()
        if result.get("sent"):
            log.info("daily digest sent to %s", result.get("recipients"))


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
