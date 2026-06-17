from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from db.schema_manager import apply_pending_migrations
from .alert_channels import send_console_alert, send_email_alert, send_webhook_alert


SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, default=str)


def _json_loads(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_to_alert(row: sqlite3.Row) -> dict:
    payload = dict(row)
    payload["payload_json"] = _json_loads(payload.get("payload_json"))
    return payload


def create_alert(
    db_path: str,
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    payload: dict | None = None,
    source: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> dict:
    normalized_severity = str(severity or "info").lower()
    if normalized_severity not in SEVERITY_ORDER:
        normalized_severity = "info"
    alert_id = f"alert:{uuid4().hex}"
    created_at = _now_iso()
    try:
        apply_pending_migrations(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO alert_events (
                    alert_id, created_at, severity, alert_type, title, message,
                    source, entity_type, entity_id, payload_json, delivery_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    created_at,
                    normalized_severity,
                    str(alert_type),
                    str(title),
                    str(message),
                    source,
                    entity_type,
                    entity_id,
                    _json_dumps(payload),
                    "created",
                ),
            )
            row = conn.execute("SELECT * FROM alert_events WHERE alert_id = ?", (alert_id,)).fetchone()
        return {"ok": True, "alert": _row_to_alert(row), "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "alert": None, "error": str(exc)}


def list_alerts(
    db_path: str,
    limit: int = 50,
    severity: str | None = None,
) -> dict:
    try:
        apply_pending_migrations(db_path)
        params: list[Any] = []
        where = ""
        if severity:
            where = "WHERE severity = ?"
            params.append(str(severity).lower())
        params.append(max(1, min(int(limit or 50), 500)))
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM alert_events
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        alerts = [_row_to_alert(row) for row in rows]
        severity_counts: dict[str, int] = {}
        for alert in alerts:
            severity_counts[alert["severity"]] = severity_counts.get(alert["severity"], 0) + 1
        return {"ok": True, "count": len(alerts), "alerts": alerts, "severity_counts": severity_counts, "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "count": 0, "alerts": [], "severity_counts": {}, "error": str(exc)}


def _channels(config: dict | None) -> list[str]:
    supplied = config if isinstance(config, dict) else {}
    raw = supplied.get("ALERT_CHANNELS") or os.getenv("ALERT_CHANNELS", "local")
    return [item.strip().lower() for item in str(raw).split(",") if item.strip()]


def process_alerts(
    db_path: str,
    alerts: list[dict],
    config: dict | None = None,
) -> dict:
    supplied = config if isinstance(config, dict) else {}
    enabled = str(supplied.get("ALERTS_ENABLED") or os.getenv("ALERTS_ENABLED", "true")).lower() in {"1", "true", "yes", "y", "on"}
    min_severity = str(supplied.get("ALERT_MIN_SEVERITY") or os.getenv("ALERT_MIN_SEVERITY", "warning")).lower()
    min_rank = SEVERITY_ORDER.get(min_severity, 1)
    stored: list[dict] = []
    deliveries: list[dict] = []
    if not enabled:
        return {"ok": True, "stored_alerts": [], "deliveries": [], "warning": "Alerts are disabled.", "errors": []}

    for alert in alerts if isinstance(alerts, list) else []:
        if not isinstance(alert, dict):
            continue
        severity = str(alert.get("severity", "info")).lower()
        if SEVERITY_ORDER.get(severity, 0) < min_rank:
            continue
        created = create_alert(
            db_path=db_path,
            severity=severity,
            alert_type=str(alert.get("alert_type") or "generic"),
            title=str(alert.get("title") or "Alert"),
            message=str(alert.get("message") or ""),
            payload=alert.get("payload") if isinstance(alert.get("payload"), dict) else alert,
            source=alert.get("source"),
            entity_type=alert.get("entity_type"),
            entity_id=alert.get("entity_id"),
        )
        if created.get("ok"):
            stored_alert = created["alert"]
            stored.append(stored_alert)
            for channel in _channels(supplied):
                if channel == "local":
                    deliveries.append(send_console_alert(stored_alert, config=supplied))
                elif channel == "webhook":
                    deliveries.append(send_webhook_alert(stored_alert, config=supplied))
                elif channel == "email":
                    deliveries.append(send_email_alert(stored_alert, config=supplied))
        else:
            deliveries.append({"ok": False, "channel": "sqlite", "delivery_status": "failed", "error": created.get("error")})
    return {
        "ok": not any(delivery.get("ok") is False for delivery in deliveries),
        "stored_alerts": stored,
        "deliveries": deliveries,
        "errors": [delivery.get("error") for delivery in deliveries if delivery.get("error")],
    }
