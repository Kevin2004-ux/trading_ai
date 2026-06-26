import sqlite3

from db.migrations import MIGRATIONS, migration_checksum
from db.schema_manager import apply_pending_migrations


def test_migration_definitions_have_versions_names_and_checksums():
    versions = [migration["version"] for migration in MIGRATIONS]

    assert len(versions) == len(set(versions))
    assert "001_schema_migrations" in versions
    assert "002_audit_events" in versions
    assert "003_pipeline_runs" in versions
    assert "004_pipeline_checkpoints" in versions
    assert "005_trade_tracking_tables" in versions
    assert "006_correlation_snapshots" in versions
    assert "007_memory_feedback_tables" in versions
    assert "008_scheduled_jobs_and_alerts" in versions
    assert "009_research_learning_tables" in versions
    assert all(migration["name"] for migration in MIGRATIONS)
    assert all(migration_checksum(migration["sql"]) for migration in MIGRATIONS)


def test_migration_tables_exist_after_apply(tmp_path):
    db_path = str(tmp_path / "migrations.db")

    result = apply_pending_migrations(db_path)

    assert result["ok"] is True
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert {
        "schema_migrations",
        "audit_events",
        "pipeline_runs",
        "pipeline_checkpoints",
        "correlation_snapshots",
        "human_annotations",
        "memory_retrieval_events",
        "scheduled_job_runs",
        "alert_events",
        "research_execution_records",
        "candidate_snapshots",
        "candidate_forward_outcomes",
        "research_policies",
        "policy_evaluations",
        "policy_proposals",
        "shadow_policy_scores",
    }.issubset(tables)
