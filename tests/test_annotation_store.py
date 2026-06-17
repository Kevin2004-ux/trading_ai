import sqlite3

from db.schema_manager import apply_pending_migrations
from memory.annotation_store import (
    add_human_annotation,
    list_human_annotations,
    list_memory_retrieval_events,
    record_memory_retrieval_event,
    summarize_annotations,
)


def test_annotations_can_be_added_listed_and_summarized(tmp_path):
    db_path = str(tmp_path / "annotations.db")

    added = add_human_annotation(
        db_path=db_path,
        entity_type="trade",
        annotation_type="setup_review",
        ticker="AAPL",
        setup_type="relative_strength",
        rating=-1,
        label="bad setup",
        notes="Failed in weak regime.",
    )
    listed = list_human_annotations(db_path, ticker="AAPL")
    summary = summarize_annotations(db_path, ticker="AAPL", setup_type="relative_strength")

    assert added["ok"] is True
    assert listed["count"] == 1
    assert summary["negative_count"] == 1
    assert summary["average_rating"] == -1


def test_blocking_annotation_is_summarized(tmp_path):
    db_path = str(tmp_path / "blocking.db")
    add_human_annotation(db_path, "trade", "blocking", ticker="TSLA", setup_type="breakout", label="blocking")

    summary = summarize_annotations(db_path, ticker="TSLA")

    assert summary["blocking_count"] == 1


def test_retrieval_events_are_recorded_and_listed(tmp_path):
    db_path = str(tmp_path / "events.db")

    recorded = record_memory_retrieval_event(
        db_path=db_path,
        run_id="run-1",
        ticker="AAPL",
        setup_type="relative_strength",
        query={"ticker": "AAPL"},
        retrieval_result={"ok": True, "matches": []},
        retrieval_quality={"quality_status": "fail"},
        used_for_decision=False,
        used_for_explanation=False,
    )
    listed = list_memory_retrieval_events(db_path, limit=10)

    assert recorded["ok"] is True
    assert listed["count"] == 1
    assert listed["events"][0]["query_json"]["ticker"] == "AAPL"


def test_memory_tables_exist_after_migrations(tmp_path):
    db_path = str(tmp_path / "migrations.db")
    result = apply_pending_migrations(db_path)

    assert result["ok"] is True
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    assert "human_annotations" in tables
    assert "memory_retrieval_events" in tables
