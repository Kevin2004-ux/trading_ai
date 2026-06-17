from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from db.schema_manager import apply_pending_migrations


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _hash_event(
    *,
    event_id: str,
    run_id: str | None,
    event_type: str,
    entity_type: str | None,
    entity_id: str | None,
    created_at: str,
    payload_json: str,
    previous_hash: str | None,
) -> str:
    content = {
        "event_id": event_id,
        "run_id": run_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "created_at": created_at,
        "payload_json": payload_json,
        "previous_hash": previous_hash,
    }
    return hashlib.sha256(_json(content).encode("utf-8")).hexdigest()


def append_audit_event(
    db_path: str,
    event_type: str,
    payload: dict,
    run_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            previous_row = conn.execute(
                "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous_row["event_hash"] if previous_row else None
            event_id = str(uuid.uuid4())
            created_at = _now_iso()
            payload_json = _json(payload)
            event_hash = _hash_event(
                event_id=event_id,
                run_id=run_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                created_at=created_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            cursor = conn.execute(
                """
                INSERT INTO audit_events (
                    event_id, run_id, event_type, entity_type, entity_id,
                    created_at, payload_json, previous_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    run_id,
                    event_type,
                    entity_type,
                    entity_id,
                    created_at,
                    payload_json,
                    previous_hash,
                    event_hash,
                ),
            )
            row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (cursor.lastrowid,)).fetchone()
        event = dict(row)
        event["payload_json"] = json.loads(event["payload_json"])
        return {"ok": True, "event": event}
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "event_type": event_type}


def list_audit_events(db_path: str, run_id: str | None = None, limit: int = 100) -> dict:
    try:
        apply_pending_migrations(db_path)
        safe_limit = max(1, min(int(limit), 500))
        with _connect(db_path) as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE run_id = ? ORDER BY id DESC LIMIT ?",
                    (run_id, safe_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            try:
                event["payload_json"] = json.loads(event["payload_json"])
            except json.JSONDecodeError:
                pass
            events.append(event)
        return {"ok": True, "events": events, "count": len(events)}
    except sqlite3.Error as exc:
        return {"ok": False, "events": [], "count": 0, "error": str(exc)}


def verify_audit_chain(db_path: str) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM audit_events ORDER BY id ASC").fetchall()
        previous_hash = None
        errors: list[dict] = []
        for row in rows:
            event = dict(row)
            if event["previous_hash"] != previous_hash:
                errors.append(
                    {
                        "event_id": event["event_id"],
                        "type": "previous_hash_mismatch",
                        "expected": previous_hash,
                        "actual": event["previous_hash"],
                    }
                )
                break
            expected_hash = _hash_event(
                event_id=event["event_id"],
                run_id=event["run_id"],
                event_type=event["event_type"],
                entity_type=event["entity_type"],
                entity_id=event["entity_id"],
                created_at=event["created_at"],
                payload_json=event["payload_json"],
                previous_hash=event["previous_hash"],
            )
            if expected_hash != event["event_hash"]:
                errors.append(
                    {
                        "event_id": event["event_id"],
                        "type": "event_hash_mismatch",
                        "expected": expected_hash,
                        "actual": event["event_hash"],
                    }
                )
                break
            previous_hash = event["event_hash"]
        return {
            "ok": not errors,
            "event_count": len(rows),
            "latest_hash": previous_hash,
            "errors": errors,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "event_count": 0, "latest_hash": None, "errors": [str(exc)]}

