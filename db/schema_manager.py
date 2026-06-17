from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from db.migrations import MIGRATIONS, migration_checksum


REQUIRED_TABLES = {
    "schema_migrations",
    "audit_events",
    "pipeline_runs",
    "pipeline_checkpoints",
    "trade_recommendations",
    "scanner_runs",
    "candidate_evaluations",
    "trade_outcomes",
    "correlation_snapshots",
    "human_annotations",
    "memory_retrieval_events",
    "scheduled_job_runs",
    "alert_events",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            version TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT,
            success INTEGER NOT NULL DEFAULT 1,
            error TEXT
        )
        """
    )


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def record_migration(
    db_path: str,
    version: str,
    name: str,
    checksum: str,
    success: bool,
    error: str | None = None,
) -> dict:
    try:
        with _connect(db_path) as conn:
            _ensure_migration_table(conn)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at, checksum, success, error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(version) DO UPDATE SET
                    name = excluded.name,
                    applied_at = excluded.applied_at,
                    checksum = excluded.checksum,
                    success = excluded.success,
                    error = excluded.error
                """,
                (version, name, _now_iso(), checksum, 1 if success else 0, error),
            )
            row = conn.execute(
                "SELECT * FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
        return {"ok": True, "migration": _row_to_dict(row)}
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "version": version}


def apply_pending_migrations(db_path: str) -> dict:
    applied: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    try:
        with _connect(db_path) as conn:
            _ensure_migration_table(conn)
            existing_rows = conn.execute(
                "SELECT version, success FROM schema_migrations"
            ).fetchall()
            applied_versions = {row["version"] for row in existing_rows if row["success"]}

            for migration in MIGRATIONS:
                version = migration["version"]
                checksum = migration_checksum(migration["sql"])
                if version in applied_versions:
                    skipped.append({"version": version, "name": migration["name"]})
                    continue
                try:
                    conn.executescript(migration["sql"])
                    conn.execute(
                        """
                        INSERT INTO schema_migrations (version, name, applied_at, checksum, success, error)
                        VALUES (?, ?, ?, ?, 1, NULL)
                        ON CONFLICT(version) DO UPDATE SET
                            name = excluded.name,
                            applied_at = excluded.applied_at,
                            checksum = excluded.checksum,
                            success = 1,
                            error = NULL
                        """,
                        (version, migration["name"], _now_iso(), checksum),
                    )
                    applied.append({"version": version, "name": migration["name"], "checksum": checksum})
                except sqlite3.Error as exc:
                    error = str(exc)
                    conn.execute(
                        """
                        INSERT INTO schema_migrations (version, name, applied_at, checksum, success, error)
                        VALUES (?, ?, ?, ?, 0, ?)
                        ON CONFLICT(version) DO UPDATE SET
                            name = excluded.name,
                            applied_at = excluded.applied_at,
                            checksum = excluded.checksum,
                            success = 0,
                            error = excluded.error
                        """,
                        (version, migration["name"], _now_iso(), checksum, error),
                    )
                    failed.append({"version": version, "name": migration["name"], "error": error})
                    break
    except sqlite3.Error as exc:
        return {"ok": False, "db_path": db_path, "applied": applied, "skipped": skipped, "failed": [{"error": str(exc)}]}

    return {
        "ok": not failed,
        "db_path": db_path,
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "migration_count": len(applied) + len(skipped),
    }


def get_schema_version(db_path: str, apply_migrations: bool = True) -> dict:
    try:
        if apply_migrations:
            apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            if apply_migrations:
                _ensure_migration_table(conn)
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if not table_exists:
                return {
                    "ok": False,
                    "db_path": db_path,
                    "current_version": None,
                    "latest_migration": None,
                    "migration_count": 0,
                    "error": "schema_migrations table does not exist.",
                }
            rows = conn.execute(
                """
                SELECT version, name, applied_at, checksum
                FROM schema_migrations
                WHERE success = 1
                ORDER BY id ASC
                """
            ).fetchall()
        latest = _row_to_dict(rows[-1]) if rows else None
        return {
            "ok": True,
            "db_path": db_path,
            "current_version": latest["version"] if latest else None,
            "latest_migration": latest,
            "migration_count": len(rows),
        }
    except sqlite3.Error as exc:
        return {"ok": False, "db_path": db_path, "error": str(exc)}


def validate_schema(db_path: str, apply_migrations: bool = True) -> dict:
    migration_result = apply_pending_migrations(db_path) if apply_migrations else {
        "ok": True,
        "db_path": db_path,
        "applied": [],
        "skipped": [],
        "failed": [],
        "migration_count": 0,
        "mutated": False,
    }
    try:
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            tables = {row["name"] for row in rows}
            migrations = conn.execute("SELECT COUNT(*) AS count FROM schema_migrations WHERE success = 1").fetchone()["count"] if "schema_migrations" in tables else 0
            recent_runs = conn.execute("SELECT COUNT(*) AS count FROM pipeline_runs").fetchone()["count"] if "pipeline_runs" in tables else 0
            audit_count = conn.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] if "audit_events" in tables else 0
        missing = sorted(REQUIRED_TABLES - tables)
        return {
            "ok": not missing and migration_result.get("ok", False),
            "db_path": db_path,
            "tables": {table: table in tables for table in sorted(REQUIRED_TABLES)},
            "missing_tables": missing,
            "migration_count": migrations,
            "recent_pipeline_runs_count": recent_runs,
            "audit_events_count": audit_count,
            "migration_result": migration_result,
            "errors": [] if not missing else [f"Missing table: {table}" for table in missing],
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "db_path": db_path,
            "tables": {},
            "missing_tables": sorted(REQUIRED_TABLES),
            "migration_count": 0,
            "recent_pipeline_runs_count": 0,
            "audit_events_count": 0,
            "migration_result": migration_result,
            "errors": [str(exc)],
        }
