"""Digest email alerting for Nimble Lab Manager.

Turns the in-app operational alerts (low stock, expiring lots, equipment service
due, POs awaiting approval, ...) into an emailed digest so they reach people who
are not staring at the app -- the whole reason a lab leaves spreadsheets behind.

Design: the alert conditions are already computed by app.api._sync_notifications,
which reconciles them into the `notification` table. This module reuses that
(never duplicating the queries), reads the current unread broadcasts, and renders
a digest. Sending is stdlib-only (smtplib) and entirely optional: with no SMTP
configured, build_digest still works (it powers the in-app preview) and
send_digest is a logged no-op, so the feature is fully demoable without a mail
server.

Configuration (environment):
  NLM_SMTP_HOST                SMTP server host (unset => sending disabled)
  NLM_SMTP_PORT                default 587
  NLM_SMTP_USER, NLM_SMTP_PASSWORD   credentials (optional for open relays)
  NLM_SMTP_FROM                From: address (default NLM_SMTP_USER)
  NLM_SMTP_TLS                 STARTTLS, default on ("0" to disable)
  NLM_DIGEST_TO                comma/semicolon-separated recipient list
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("nlm.notify")

# Grouping order + human labels for the digest sections.
_KIND_ORDER = [
    "expiring",
    "low_stock",
    "maintenance_due",
    "approval_pending",
    "compatibility",
    "other",
]
_KIND_LABELS = {
    "expiring": "Expiring / expired",
    "low_stock": "Low stock",
    "maintenance_due": "Service / calibration due",
    "approval_pending": "Purchase orders awaiting approval",
    "compatibility": "Storage-compatibility conflicts",
    "other": "Other",
}
_SEV_RANK = {"danger": 0, "warn": 1, "info": 2}


def smtp_configured():
    """True when at least an SMTP host is set (sending is possible)."""
    return bool(os.environ.get("NLM_SMTP_HOST", "").strip())


def digest_recipients():
    """Parse NLM_DIGEST_TO into a de-duplicated list of addresses."""
    raw = os.environ.get("NLM_DIGEST_TO", "")
    seen, out = set(), []
    for addr in raw.replace(";", ",").split(","):
        addr = addr.strip()
        if addr and addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    return out


def build_digest(conn, sync=True):
    """Build a structured digest of the current open alerts.

    Returns a dict: {total, urgent, groups:[{kind,label,items:[{severity,message}]}],
    subject, text, html}. When sync (the default) it reconciles notifications
    first so the digest reflects live state.
    """
    if sync:
        from .api import _sync_notifications  # local import avoids an import cycle

        _sync_notifications(conn)

    rows = conn.execute(
        """SELECT kind, severity, message
             FROM notification
            WHERE read_at IS NULL AND user_id IS NULL
            ORDER BY id"""
    ).fetchall()

    by_kind = {}
    urgent = 0
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(
            {"severity": r["severity"], "message": r["message"]}
        )
        if r["severity"] == "danger":
            urgent += 1

    groups = []
    for kind in _KIND_ORDER + [k for k in by_kind if k not in _KIND_ORDER]:
        items = by_kind.get(kind)
        if not items:
            continue
        items.sort(key=lambda it: _SEV_RANK.get(it["severity"], 3))
        groups.append(
            {
                "kind": kind,
                "label": _KIND_LABELS.get(kind, kind.replace("_", " ").capitalize()),
                "items": items,
            }
        )

    total = len(rows)
    subject = _subject(total, urgent)
    return {
        "total": total,
        "urgent": urgent,
        "groups": groups,
        "subject": subject,
        "text": _render_text(subject, groups, total),
        "html": _render_html(subject, groups, total, urgent),
    }


def send_digest(conn, to=None, force_when_empty=False):
    """Build and email the digest. Returns a result dict describing what happened
    (and always includes the digest, so callers can preview it either way):
    {sent: bool, reason: str, recipients: [...], total, urgent}.

    No-ops safely (sent=False) when there is nothing to report, no recipients are
    configured, or SMTP is not configured -- so it is harmless to call anywhere.
    """
    digest = build_digest(conn)
    base = {
        "sent": False,
        "digest": digest,
        "total": digest["total"],
        "urgent": digest["urgent"],
        "recipients": [],
    }

    if digest["total"] == 0 and not force_when_empty:
        return {**base, "reason": "no-open-alerts"}

    recipients = list(to) if to else digest_recipients()
    if not recipients:
        return {**base, "reason": "no-recipients"}
    if not smtp_configured():
        return {**base, "reason": "smtp-not-configured", "recipients": recipients}

    try:
        _smtp_send(recipients, digest["subject"], digest["text"], digest["html"])
    except Exception as exc:  # noqa: BLE001 -- report any delivery failure, don't crash
        log.warning("digest send failed: %s", exc)
        return {**base, "reason": f"smtp-error: {exc}", "recipients": recipients}

    log.info("sent alert digest (%d alerts) to %s", digest["total"], recipients)
    return {**base, "sent": True, "reason": "sent", "recipients": recipients}


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _subject(total, urgent):
    if total == 0:
        return "Nimble Lab: all clear"
    tail = f" ({urgent} urgent)" if urgent else ""
    noun = "alert" if total == 1 else "alerts"
    return f"Nimble Lab: {total} open {noun}{tail}"


def _render_text(subject, groups, total):
    lines = [subject, "=" * len(subject), ""]
    if total == 0:
        lines.append("No open alerts. Nothing needs attention right now.")
    for g in groups:
        lines.append(f"{g['label']} ({len(g['items'])})")
        for it in g["items"]:
            mark = "!!" if it["severity"] == "danger" else "* "
            lines.append(f"  {mark} {it['message']}")
        lines.append("")
    lines.append("-- Nimble Lab Manager")
    return "\n".join(lines)


def _esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_html(subject, groups, total, urgent):
    # Self-contained inline styles; spartan, email-client-safe.
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#111;max-width:640px">',
        f'<h2 style="margin:0 0 4px">{_esc(subject)}</h2>',
    ]
    if total == 0:
        parts.append(
            '<p style="color:#555">No open alerts. Nothing needs attention '
            "right now.</p>"
        )
    for g in groups:
        parts.append(
            f'<h3 style="margin:18px 0 6px;border-bottom:1px solid #ddd;'
            f'padding-bottom:4px">{_esc(g["label"])} '
            f'<span style="color:#888;font-weight:normal">({len(g["items"])})</span></h3>'
        )
        parts.append('<ul style="margin:0;padding-left:18px">')
        for it in g["items"]:
            color = "#b00020" if it["severity"] == "danger" else "#8a6d00"
            parts.append(
                f'<li style="margin:3px 0;color:{color}">{_esc(it["message"])}</li>'
            )
        parts.append("</ul>")
    parts.append(
        '<p style="margin-top:20px;color:#888;font-size:12px">'
        "Sent by Nimble Lab Manager. This digest lists the alerts currently open "
        "in the app.</p>"
    )
    parts.append("</div>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
def _smtp_send(recipients, subject, text, html):
    host = os.environ["NLM_SMTP_HOST"].strip()
    port = int(os.environ.get("NLM_SMTP_PORT", "587") or "587")
    user = os.environ.get("NLM_SMTP_USER", "").strip()
    password = os.environ.get("NLM_SMTP_PASSWORD", "")
    sender = os.environ.get("NLM_SMTP_FROM", "").strip() or user or "nimble@localhost"
    use_tls = os.environ.get("NLM_SMTP_TLS", "1").strip().lower() not in ("0", "false", "no", "off")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as server:
        if use_tls:
            server.starttls(context=ssl.create_default_context())
        if user:
            server.login(user, password)
        server.send_message(msg, from_addr=sender, to_addrs=recipients)
