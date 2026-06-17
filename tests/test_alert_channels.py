from alerts.alert_channels import send_console_alert, send_email_alert, send_webhook_alert


def test_console_alert_is_local_delivery_only():
    result = send_console_alert({"alert_id": "alert-1", "severity": "warning", "title": "Test"})

    assert result["ok"] is True
    assert result["channel"] == "local"
    assert result["delivery_status"] == "delivered"


def test_webhook_alert_is_disabled_without_url(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)

    result = send_webhook_alert({"alert_id": "alert-1"})

    assert result["ok"] is True
    assert result["channel"] == "webhook"
    assert result["delivery_status"] == "disabled"


def test_webhook_alert_does_not_send_externally_by_default():
    result = send_webhook_alert(
        {"alert_id": "alert-1"},
        config={"ALERT_WEBHOOK_URL": "https://example.test/hook"},
    )

    assert result["ok"] is True
    assert result["delivery_status"] == "configured_not_sent"


def test_email_alert_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_ENABLED", raising=False)

    result = send_email_alert({"alert_id": "alert-1"})

    assert result["ok"] is True
    assert result["channel"] == "email"
    assert result["delivery_status"] == "disabled"
