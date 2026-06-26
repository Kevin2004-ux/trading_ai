import sqlite3

from db.migrations import MIGRATIONS
from db.schema_manager import (
    apply_pending_migrations,
    get_schema_version,
    record_migration,
    validate_schema,
)


def test_schema_migrations_apply_cleanly_to_empty_db(tmp_path):
    db_path = str(tmp_path / "schema.db")

    result = apply_pending_migrations(db_path)
    validation = validate_schema(db_path)
    version = get_schema_version(db_path)

    assert result["ok"] is True
    assert validation["ok"] is True
    assert version["current_version"] == MIGRATIONS[-1]["version"]
    assert validation["tables"]["audit_events"] is True
    assert validation["tables"]["pipeline_runs"] is True
    assert validation["tables"]["scheduled_job_runs"] is True
    assert validation["tables"]["alert_events"] is True
    assert validation["tables"]["research_execution_records"] is True
    assert validation["tables"]["candidate_snapshots"] is True
    assert validation["tables"]["candidate_forward_outcomes"] is True
    assert validation["tables"]["research_policies"] is True
    assert validation["tables"]["policy_evaluations"] is True
    assert validation["tables"]["policy_proposals"] is True
    assert validation["tables"]["shadow_policy_scores"] is True


def test_schema_migrations_are_idempotent(tmp_path):
    db_path = str(tmp_path / "schema_idempotent.db")

    first = apply_pending_migrations(db_path)
    second = apply_pending_migrations(db_path)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["applied"] == []
    assert second["migration_count"] >= 5


def test_record_failed_migration_is_preserved(tmp_path):
    db_path = str(tmp_path / "schema_failed.db")
    apply_pending_migrations(db_path)

    result = record_migration(
        db_path,
        version="999_bad_migration",
        name="Bad migration",
        checksum="bad",
        success=False,
        error="boom",
    )

    assert result["ok"] is True
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT success, error FROM schema_migrations WHERE version = ?",
            ("999_bad_migration",),
        ).fetchone()
    assert row == (0, "boom")
