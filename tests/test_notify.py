"""Tests for the email alert digest (app.notify) and its API endpoints.

The digest reuses the app's existing alert engine, renders text/HTML, and sends
via smtplib only when configured -- so these tests exercise building, the
no-op/error paths, a monkeypatched send, and the preview/send endpoints with
role gating. No real SMTP server is involved.
"""

import app.notify as notify


def test_build_digest_reflects_low_stock(db):
    db.execute(
        "UPDATE inventory SET quantity_on_hand = 0, reorder_threshold = 5 "
        "WHERE item_id = 1"
    )
    db.commit()
    digest = notify.build_digest(db)
    assert digest["total"] > 0
    low = next((g for g in digest["groups"] if g["kind"] == "low_stock"), None)
    assert low is not None and low["items"]
    # subject + both body renderings are populated
    assert "Nimble Lab" in digest["subject"]
    assert digest["text"] and "<" in digest["html"]


def test_send_digest_no_recipients(db, monkeypatch):
    monkeypatch.delenv("NLM_DIGEST_TO", raising=False)
    # force an alert to exist so we get past the "nothing to report" gate
    db.execute("UPDATE inventory SET quantity_on_hand = 0 WHERE item_id = 1")
    db.commit()
    result = notify.send_digest(db)
    assert result["sent"] is False
    assert result["reason"] == "no-recipients"


def test_send_digest_smtp_not_configured(db, monkeypatch):
    monkeypatch.setenv("NLM_DIGEST_TO", "lab@example.com")
    monkeypatch.delenv("NLM_SMTP_HOST", raising=False)
    db.execute("UPDATE inventory SET quantity_on_hand = 0 WHERE item_id = 1")
    db.commit()
    result = notify.send_digest(db)
    assert result["sent"] is False
    assert result["reason"] == "smtp-not-configured"
    assert result["recipients"] == ["lab@example.com"]


def test_send_digest_delivers_when_configured(db, monkeypatch):
    monkeypatch.setenv("NLM_DIGEST_TO", "a@example.com, b@example.com")
    monkeypatch.setenv("NLM_SMTP_HOST", "smtp.example.com")
    db.execute("UPDATE inventory SET quantity_on_hand = 0 WHERE item_id = 1")
    db.commit()

    captured = {}

    def fake_send(recipients, subject, text, html):
        captured["recipients"] = recipients
        captured["subject"] = subject

    monkeypatch.setattr(notify, "_smtp_send", fake_send)
    result = notify.send_digest(db)
    assert result["sent"] is True
    assert result["reason"] == "sent"
    assert captured["recipients"] == ["a@example.com", "b@example.com"]


def test_send_digest_reports_transport_error(db, monkeypatch):
    monkeypatch.setenv("NLM_DIGEST_TO", "a@example.com")
    monkeypatch.setenv("NLM_SMTP_HOST", "smtp.example.com")
    db.execute("UPDATE inventory SET quantity_on_hand = 0 WHERE item_id = 1")
    db.commit()

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(notify, "_smtp_send", boom)
    result = notify.send_digest(db)
    assert result["sent"] is False
    assert result["reason"].startswith("smtp-error")


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
def test_preview_endpoint_role_gated(manager, member):
    r = manager.get("/api/notifications/digest/preview")
    assert r.status_code == 200
    body = r.json()
    assert "groups" in body and "total" in body and "email_configured" in body
    assert member.get("/api/notifications/digest/preview").status_code == 403


def test_send_endpoint_admin_only(admin, manager, monkeypatch):
    monkeypatch.delenv("NLM_DIGEST_TO", raising=False)
    assert manager.post("/api/notifications/digest/send").status_code == 403
    r = admin.post("/api/notifications/digest/send")
    assert r.status_code == 200
    # no recipients configured in the test env -> clear, non-error feedback
    assert r.json()["sent"] is False
    assert r.json()["reason"] in ("no-recipients", "smtp-not-configured")
