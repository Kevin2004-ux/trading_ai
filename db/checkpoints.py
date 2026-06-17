from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
import time
import uuid
from typing import Any

from db.schema_manager import apply_pending_migrations


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _deserialize(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _run_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["summary_json"] = _deserialize(item.get("summary_json"))
    item["error_json"] = _deserialize(item.get("error_json"))
    return item


def _checkpoint_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["payload_json"] = _deserialize(item.get("payload_json"))
    item["error_json"] = _deserialize(item.get("error_json"))
    return item


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _counts_from_summary(summary: dict) -> dict:
    scan = summary.get("scan_execution_summary") if isinstance(summary, dict) else None
    if not isinstance(scan, dict):
        scan = summary.get("scan_summary") if isinstance(summary, dict) else {}
    return {
        "total_tickers": _safe_int(scan.get("total_tickers") if isinstance(scan, dict) else summary.get("tickers_scanned")),
        "completed_tickers": _safe_int(scan.get("completed_tickers") if isinstance(scan, dict) else None),
        "failed_tickers": len(scan.get("failed_tickers", [])) if isinstance(scan, dict) and isinstance(scan.get("failed_tickers"), list) else _safe_int(summary.get("failed_ticker_count")),
        "timed_out_tickers": len(scan.get("timed_out_tickers", [])) if isinstance(scan, dict) and isinstance(scan.get("timed_out_tickers"), list) else _safe_int(summary.get("timed_out_ticker_count")),
        "selected_count": _safe_int(summary.get("selected_count")),
        "logged_count": _safe_int(summary.get("logged_count")),
        "partial_results_used": 1 if isinstance(scan, dict) and scan.get("partial_results_used") else 0,
        "duration_seconds": _safe_float(scan.get("duration_seconds") if isinstance(scan, dict) else None),
    }


def start_pipeline_run(db_path: str, run_type: str, metadata: dict | None = None) -> dict:
    try:
        apply_pending_migrations(db_path)
        run_id = f"{run_type}_{uuid.uuid4().hex}"
        started_at = _now_iso()
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs (run_id, run_type, status, started_at, summary_json)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, run_type, started_at, _serialize(metadata or {})),
            )
        return get_pipeline_run(db_path, run_id)
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "run_id": None}


def complete_pipeline_run(db_path: str, run_id: str, summary: dict, status: str = "completed") -> dict:
    try:
        apply_pending_migrations(db_path)
        completed_at = _now_iso()
        counts = _counts_from_summary(summary)
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT started_at FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            started_at = row["started_at"] if row else None
            duration = counts.get("duration_seconds")
            if duration is None and started_at:
                try:
                    duration = time.time() - datetime.fromisoformat(started_at).timestamp()
                except ValueError:
                    duration = None
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    completed_at = ?,
                    duration_seconds = ?,
                    total_tickers = ?,
                    completed_tickers = ?,
                    failed_tickers = ?,
                    timed_out_tickers = ?,
                    selected_count = ?,
                    logged_count = ?,
                    partial_results_used = ?,
                    summary_json = ?,
                    error_json = NULL
                WHERE run_id = ?
                """,
                (
                    status,
                    completed_at,
                    duration,
                    counts["total_tickers"],
                    counts["completed_tickers"],
                    counts["failed_tickers"],
                    counts["timed_out_tickers"],
                    counts["selected_count"],
                    counts["logged_count"],
                    counts["partial_results_used"],
                    _serialize(summary),
                    run_id,
                ),
            )
        return get_pipeline_run(db_path, run_id)
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "run_id": run_id}


def fail_pipeline_run(db_path: str, run_id: str, error: dict) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = 'failed',
                    completed_at = ?,
                    error_json = ?
                WHERE run_id = ?
                """,
                (_now_iso(), _serialize(error), run_id),
            )
        return get_pipeline_run(db_path, run_id)
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "run_id": run_id}


def get_pipeline_run(db_path: str, run_id: str) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return {"ok": row is not None, "pipeline_run": _run_row_to_dict(row), "run_id": run_id}
    except sqlite3.Error as exc:
        return {"ok": False, "pipeline_run": None, "run_id": run_id, "error": str(exc)}


def list_recent_pipeline_runs(db_path: str, limit: int = 20) -> dict:
    try:
        apply_pending_migrations(db_path)
        safe_limit = max(1, min(int(limit), 200))
        with _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        runs = [_run_row_to_dict(row) for row in rows]
        return {"ok": True, "pipeline_runs": runs, "count": len(runs)}
    except sqlite3.Error as exc:
        return {"ok": False, "pipeline_runs": [], "count": 0, "error": str(exc)}


def record_checkpoint(
    db_path: str,
    run_id: str,
    checkpoint_name: str,
    status: str,
    payload: dict | None = None,
    error: dict | None = None,
) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO pipeline_checkpoints (
                    run_id, checkpoint_name, status, created_at, payload_json, error_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, checkpoint_name, status, _now_iso(), _serialize(payload), _serialize(error)),
            )
            row = conn.execute("SELECT * FROM pipeline_checkpoints WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return {"ok": True, "checkpoint": _checkpoint_row_to_dict(row)}
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "run_id": run_id, "checkpoint_name": checkpoint_name}


def list_checkpoints(db_path: str, run_id: str) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_checkpoints WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        checkpoints = [_checkpoint_row_to_dict(row) for row in rows]
        return {"ok": True, "run_id": run_id, "checkpoints": checkpoints, "count": len(checkpoints)}
    except sqlite3.Error as exc:
        return {"ok": False, "run_id": run_id, "checkpoints": [], "count": 0, "error": str(exc)}


def get_latest_checkpoint(db_path: str, run_id: str) -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_checkpoints WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return {"ok": row is not None, "run_id": run_id, "checkpoint": _checkpoint_row_to_dict(row)}
    except sqlite3.Error as exc:
        return {"ok": False, "run_id": run_id, "checkpoint": None, "error": str(exc)}

