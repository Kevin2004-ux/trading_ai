from __future__ import annotations

import os
from typing import Any


def _disabled(channel: str) -> dict:
    return {
        "ok": True,
        "channel": channel,
        "delivery_status": "disabled",
        "error": None,
    }


def send_console_alert(alert: dict, config: dict | None = None) -> dict:
    return {
        "ok": True,
        "channel": "local",
        "delivery_status": "delivered",
        "alert_id": (alert or {}).get("alert_id"),
        "severity": (alert or {}).get("severity"),
        "title": (alert or {}).get("title"),
        "error": None,
    }


def send_webhook_alert(alert: dict, config: dict | None = None) -> dict:
    supplied = config if isinstance(config, dict) else {}
    webhook_url = supplied.get("ALERT_WEBHOOK_URL") or os.getenv("ALERT_WEBHOOK_URL")
    if not webhook_url:
        return _disabled("webhook")
    # Intentionally no real network send by default. Tests can monkeypatch this function.
    if not supplied.get("allow_external_send"):
        return {
            "ok": True,
            "channel": "webhook",
            "delivery_status": "configured_not_sent",
            "error": None,
        }
    return {
        "ok": False,
        "channel": "webhook",
        "delivery_status": "not_implemented",
        "error": "Webhook sending is disabled unless a project-specific sender is injected.",
    }


def send_email_alert(alert: dict, config: dict | None = None) -> dict:
    supplied = config if isinstance(config, dict) else {}
    email_enabled = str(supplied.get("ALERT_EMAIL_ENABLED") or os.getenv("ALERT_EMAIL_ENABLED", "false")).lower() in {"1", "true", "yes", "y", "on"}
    if not email_enabled:
        return _disabled("email")
    if not supplied.get("allow_external_send"):
        return {
            "ok": True,
            "channel": "email",
            "delivery_status": "configured_not_sent",
            "error": None,
        }
    return {
        "ok": False,
        "channel": "email",
        "delivery_status": "not_implemented",
        "error": "Email sending is disabled unless a project-specific sender is injected.",
    }
