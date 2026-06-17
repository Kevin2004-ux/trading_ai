from __future__ import annotations

import json
import sqlite3
from typing import Any

from db.schema_manager import apply_pending_migrations


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], sort_keys=True, default=str)


def _json_loads(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_to_run(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    for key in ("result_json", "warning_json", "error_json"):
        payload[key] = _json_loads(payload.get(key))
    return payload


def record_job_run(
    db_path: str,
    job_run_id: str,
    job_name: str,
    job_type: str,
    status: str,
    started_at: str,
    completed_at: str | None = None,
    duration_seconds: float | None = None,
    dry_run: bool = True,
    result: dict | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    try:
        apply_pending_migrations(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO scheduled_job_runs (
                    job_run_id, job_name, job_type, status, started_at, completed_at,
                    duration_seconds, dry_run, result_json, warning_json, error_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_run_id) DO UPDATE SET
                    status = excluded.status,
                    completed_at = excluded.completed_at,
                    duration_seconds = excluded.duration_seconds,
                    result_json = excluded.result_json,
                    warning_json = excluded.warning_json,
                    error_json = excluded.error_json
                """,
                (
                    job_run_id,
                    job_name,
                    job_type,
                    status,
                    started_at,
                    completed_at,
                    duration_seconds,
                    1 if dry_run else 0,
                    _json_dumps(result or {}),
                    _json_dumps(warnings or []),
                    _json_dumps(errors or []),
                ),
            )
            row = conn.execute("SELECT * FROM scheduled_job_runs WHERE job_run_id = ?", (job_run_id,)).fetchone()
        return {"ok": True, "job_run": _row_to_run(row), "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "job_run": None, "error": str(exc)}


def list_job_runs(db_path: str, limit: int = 50) -> dict:
    try:
        apply_pending_migrations(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM scheduled_job_runs
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit or 50), 500)),),
            ).fetchall()
        runs = [_row_to_run(row) for row in rows]
        return {"ok": True, "count": len(runs), "job_runs": runs, "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "count": 0, "job_runs": [], "error": str(exc)}


def get_job_run(db_path: str, job_run_id: str) -> dict:
    try:
        apply_pending_migrations(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM scheduled_job_runs WHERE job_run_id = ?", (job_run_id,)).fetchone()
        run = _row_to_run(row)
        return {"ok": run is not None, "job_run": run, "error": None if run else "Job run not found."}
    except sqlite3.Error as exc:
        return {"ok": False, "job_run": None, "error": str(exc)}
