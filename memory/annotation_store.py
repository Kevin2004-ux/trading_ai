from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


def _json_loads(value: Any) -> Any:
    if not isinstance(value, str) or value == "":
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _dict_from_row(row: sqlite3.Row) -> dict:
    payload = dict(row)
    for key in ("payload_json", "query_json", "retrieval_result_json", "retrieval_quality_json"):
        if key in payload:
            payload[key] = _json_loads(payload.get(key))
    return payload


def init_annotation_db(db_path: str) -> dict:
    try:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS human_annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    annotation_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT,
                    ticker TEXT,
                    setup_type TEXT,
                    annotation_type TEXT NOT NULL,
                    rating INTEGER,
                    label TEXT,
                    notes TEXT,
                    payload_json TEXT,
                    source TEXT DEFAULT 'human'
                );

                CREATE INDEX IF NOT EXISTS idx_human_annotations_ticker
                ON human_annotations(ticker);

                CREATE INDEX IF NOT EXISTS idx_human_annotations_setup_type
                ON human_annotations(setup_type);

                CREATE TABLE IF NOT EXISTS memory_retrieval_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    run_id TEXT,
                    ticker TEXT,
                    setup_type TEXT,
                    query_json TEXT,
                    retrieval_result_json TEXT,
                    retrieval_quality_json TEXT,
                    used_for_decision INTEGER DEFAULT 0,
                    used_for_explanation INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_memory_retrieval_events_created_at
                ON memory_retrieval_events(created_at);

                CREATE INDEX IF NOT EXISTS idx_memory_retrieval_events_ticker
                ON memory_retrieval_events(ticker);
                """
            )
        return {"ok": True, "db_path": db_path, "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "db_path": db_path, "error": str(exc)}


def add_human_annotation(
    db_path: str,
    entity_type: str,
    annotation_type: str,
    rating: int | None = None,
    label: str | None = None,
    notes: str | None = None,
    entity_id: str | None = None,
    ticker: str | None = None,
    setup_type: str | None = None,
    payload: dict | None = None,
) -> dict:
    init_result = init_annotation_db(db_path)
    if not init_result.get("ok"):
        return init_result
    annotation_id = f"annotation:{uuid4().hex}"
    created_at = _now_iso()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO human_annotations (
                    annotation_id, created_at, entity_type, entity_id, ticker, setup_type,
                    annotation_type, rating, label, notes, payload_json, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    annotation_id,
                    created_at,
                    str(entity_type),
                    entity_id,
                    str(ticker).upper() if ticker else None,
                    setup_type,
                    str(annotation_type),
                    rating,
                    label,
                    notes,
                    _json_dumps(payload),
                    "human",
                ),
            )
            row = conn.execute(
                "SELECT * FROM human_annotations WHERE annotation_id = ?",
                (annotation_id,),
            ).fetchone()
        return {"ok": True, "annotation": _dict_from_row(row), "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "annotation": None, "error": str(exc)}


def list_human_annotations(
    db_path: str,
    ticker: str | None = None,
    setup_type: str | None = None,
    limit: int = 50,
) -> dict:
    init_result = init_annotation_db(db_path)
    if not init_result.get("ok"):
        return init_result
    clauses: list[str] = []
    params: list[Any] = []
    if ticker:
        clauses.append("ticker = ?")
        params.append(str(ticker).upper())
    if setup_type:
        clauses.append("setup_type = ?")
        params.append(setup_type)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(int(limit or 50), 1))
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM human_annotations
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        annotations = [_dict_from_row(row) for row in rows]
        return {"ok": True, "count": len(annotations), "annotations": annotations, "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "count": 0, "annotations": [], "error": str(exc)}


def summarize_annotations(
    db_path: str,
    ticker: str | None = None,
    setup_type: str | None = None,
) -> dict:
    listed = list_human_annotations(db_path, ticker=ticker, setup_type=setup_type, limit=500)
    if not listed.get("ok"):
        return listed
    annotations = listed.get("annotations", [])
    positive = [item for item in annotations if (item.get("rating") or 0) > 0 or str(item.get("label") or "").lower() in {"good setup", "positive", "supportive"}]
    negative = [item for item in annotations if (item.get("rating") or 0) < 0 or str(item.get("label") or "").lower() in {"bad setup", "negative", "caution"}]
    blocking = [item for item in annotations if str(item.get("label") or "").lower() == "blocking" or str(item.get("annotation_type") or "").lower() == "blocking"]
    ratings = [item.get("rating") for item in annotations if isinstance(item.get("rating"), int)]
    average_rating = round(sum(ratings) / len(ratings), 4) if ratings else None
    labels: dict[str, int] = {}
    for item in annotations:
        label = str(item.get("label") or "unlabeled")
        labels[label] = labels.get(label, 0) + 1
    return {
        "ok": True,
        "ticker": str(ticker).upper() if ticker else None,
        "setup_type": setup_type,
        "total_annotations": len(annotations),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "blocking_count": len(blocking),
        "average_rating": average_rating,
        "labels": labels,
        "recent_annotations": annotations[:10],
        "error": None,
    }


def record_memory_retrieval_event(
    db_path: str,
    run_id: str | None,
    ticker: str,
    setup_type: str | None,
    query: dict,
    retrieval_result: dict,
    retrieval_quality: dict,
    used_for_decision: bool,
    used_for_explanation: bool,
) -> dict:
    init_result = init_annotation_db(db_path)
    if not init_result.get("ok"):
        return init_result
    event_id = f"memory_event:{uuid4().hex}"
    created_at = _now_iso()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO memory_retrieval_events (
                    event_id, created_at, run_id, ticker, setup_type, query_json,
                    retrieval_result_json, retrieval_quality_json, used_for_decision,
                    used_for_explanation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    created_at,
                    run_id,
                    str(ticker or "").upper(),
                    setup_type,
                    _json_dumps(query),
                    _json_dumps(retrieval_result),
                    _json_dumps(retrieval_quality),
                    1 if used_for_decision else 0,
                    1 if used_for_explanation else 0,
                ),
            )
            row = conn.execute("SELECT * FROM memory_retrieval_events WHERE event_id = ?", (event_id,)).fetchone()
        return {"ok": True, "event": _dict_from_row(row), "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "event": None, "error": str(exc)}


def list_memory_retrieval_events(db_path: str, limit: int = 50) -> dict:
    init_result = init_annotation_db(db_path)
    if not init_result.get("ok"):
        return init_result
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM memory_retrieval_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(int(limit or 50), 1),),
            ).fetchall()
        events = [_dict_from_row(row) for row in rows]
        return {"ok": True, "count": len(events), "events": events, "error": None}
    except sqlite3.Error as exc:
        return {"ok": False, "count": 0, "events": [], "error": str(exc)}
