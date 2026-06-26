from __future__ import annotations

import hashlib


MIGRATIONS = [
    {
        "version": "001_schema_migrations",
        "name": "Create schema migration tracking table",
        "sql": """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            version TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT,
            success INTEGER NOT NULL DEFAULT 1,
            error TEXT
        );
        """,
    },
    {
        "version": "002_audit_events",
        "name": "Create immutable audit event log",
        "sql": """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            run_id TEXT,
            event_type TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_hash TEXT,
            event_hash TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_events_run_id
        ON audit_events(run_id);

        CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
        ON audit_events(created_at);
        """,
    },
    {
        "version": "003_pipeline_runs",
        "name": "Create pipeline run tracking table",
        "sql": """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_seconds REAL,
            total_tickers INTEGER,
            completed_tickers INTEGER,
            failed_tickers INTEGER,
            timed_out_tickers INTEGER,
            selected_count INTEGER,
            logged_count INTEGER,
            partial_results_used INTEGER DEFAULT 0,
            summary_json TEXT,
            error_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
        ON pipeline_runs(started_at);
        """,
    },
    {
        "version": "004_pipeline_checkpoints",
        "name": "Create pipeline checkpoint table",
        "sql": """
        CREATE TABLE IF NOT EXISTS pipeline_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            checkpoint_name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT,
            error_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pipeline_checkpoints_run_id
        ON pipeline_checkpoints(run_id);

        CREATE INDEX IF NOT EXISTS idx_pipeline_checkpoints_created_at
        ON pipeline_checkpoints(created_at);
        """,
    },
    {
        "version": "005_trade_tracking_tables",
        "name": "Ensure core trade tracking tables exist",
        "sql": """
        CREATE TABLE IF NOT EXISTS trade_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            strategy TEXT NOT NULL,
            setup_type TEXT,
            entry_price REAL NOT NULL,
            target_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            risk_reward REAL,
            holding_period_days INTEGER,
            expiration TEXT,
            option_contract TEXT,
            confidence REAL,
            score REAL,
            recommendation_status TEXT DEFAULT 'open',
            thesis TEXT,
            invalidation TEXT,
            data_snapshot_json TEXT,
            constraint_results_json TEXT,
            model_outputs_json TEXT,
            source TEXT DEFAULT 'ai_agent',
            status TEXT DEFAULT 'open',
            outcome TEXT,
            exit_price REAL,
            closed_at TEXT,
            max_gain REAL,
            max_drawdown REAL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS scanner_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            universe TEXT,
            total_scanned INTEGER,
            total_passed INTEGER,
            total_rejected INTEGER,
            market_data_freshness TEXT,
            config_json TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS candidate_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanner_run_id INTEGER,
            created_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            asset_type TEXT,
            direction TEXT,
            setup_type TEXT,
            passed_constraints INTEGER,
            score REAL,
            rank INTEGER,
            rejection_reason TEXT,
            failed_constraints_json TEXT,
            metrics_json TEXT,
            constraint_results_json TEXT,
            FOREIGN KEY(scanner_run_id) REFERENCES scanner_runs(id)
        );

        CREATE TABLE IF NOT EXISTS trade_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            outcome TEXT NOT NULL,
            exit_price REAL,
            exit_reason TEXT,
            realized_return REAL,
            max_gain REAL,
            max_drawdown REAL,
            grading_data_json TEXT,
            FOREIGN KEY(recommendation_id) REFERENCES trade_recommendations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_trade_recommendations_status
        ON trade_recommendations(status);

        CREATE INDEX IF NOT EXISTS idx_trade_recommendations_ticker_created_at
        ON trade_recommendations(ticker, created_at);

        CREATE INDEX IF NOT EXISTS idx_candidate_evaluations_scanner_run_id
        ON candidate_evaluations(scanner_run_id);

        CREATE INDEX IF NOT EXISTS idx_trade_outcomes_recommendation_id
        ON trade_outcomes(recommendation_id);
        """,
    },
    {
        "version": "006_correlation_snapshots",
        "name": "Create correlation snapshot table",
        "sql": """
        CREATE TABLE IF NOT EXISTS correlation_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            lookback_days INTEGER NOT NULL,
            tickers_json TEXT NOT NULL,
            matrix_json TEXT NOT NULL,
            summary_json TEXT,
            source TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_correlation_snapshots_created_at
        ON correlation_snapshots(created_at);
        """,
    },
    {
        "version": "007_memory_feedback_tables",
        "name": "Create memory retrieval and human annotation tables",
        "sql": """
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
        """,
    },
    {
        "version": "008_scheduled_jobs_and_alerts",
        "name": "Create scheduled job history and alert event tables",
        "sql": """
        CREATE TABLE IF NOT EXISTS scheduled_job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_run_id TEXT NOT NULL UNIQUE,
            job_name TEXT NOT NULL,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_seconds REAL,
            dry_run INTEGER DEFAULT 1,
            result_json TEXT,
            warning_json TEXT,
            error_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_started_at
        ON scheduled_job_runs(started_at);

        CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_job_name
        ON scheduled_job_runs(job_name);

        CREATE TABLE IF NOT EXISTS alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            severity TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            source TEXT,
            entity_type TEXT,
            entity_id TEXT,
            payload_json TEXT,
            delivery_status TEXT DEFAULT 'created'
        );

        CREATE INDEX IF NOT EXISTS idx_alert_events_created_at
        ON alert_events(created_at);

        CREATE INDEX IF NOT EXISTS idx_alert_events_severity
        ON alert_events(severity);
        """,
    },
    {
        "version": "009_research_learning_tables",
        "name": "Create point-in-time research learning tables",
        "sql": """
        CREATE TABLE IF NOT EXISTS research_execution_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_run_id TEXT NOT NULL,
            pass_run_id TEXT,
            parent_run_id TEXT,
            request_id TEXT,
            created_at TEXT NOT NULL,
            snapshot_at TEXT NOT NULL,
            plan_version TEXT,
            policy_version TEXT,
            policy_fingerprint TEXT,
            plan_fingerprint TEXT,
            requested_instrument TEXT,
            objective TEXT,
            approved_plan_json TEXT,
            execution_summary_json TEXT,
            market_regime_label TEXT,
            provider_status TEXT,
            data_status TEXT,
            pass_number INTEGER,
            adaptive_stop_reason TEXT,
            paper_trading_only INTEGER NOT NULL DEFAULT 1,
            brokerage_execution_enabled INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_research_execution_records_root_run
        ON research_execution_records(root_run_id);

        CREATE INDEX IF NOT EXISTS idx_research_execution_records_pass_run
        ON research_execution_records(pass_run_id);

        CREATE INDEX IF NOT EXISTS idx_research_execution_records_created_at
        ON research_execution_records(created_at);

        CREATE INDEX IF NOT EXISTS idx_research_execution_records_policy
        ON research_execution_records(policy_version, policy_fingerprint);

        CREATE TABLE IF NOT EXISTS candidate_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_record_id INTEGER,
            root_run_id TEXT NOT NULL,
            pass_run_id TEXT,
            parent_run_id TEXT,
            request_id TEXT,
            ticker TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            option_contract TEXT,
            setup_type TEXT,
            scan_profile TEXT,
            direction TEXT,
            actionability_status TEXT,
            rank INTEGER,
            engine_score REAL,
            opportunity_score REAL,
            opportunity_score_version TEXT,
            opportunity_components_json TEXT,
            data_confidence REAL,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            risk_reward REAL,
            underlying_price REAL,
            expiration TEXT,
            days_to_expiration INTEGER,
            bid REAL,
            ask REAL,
            mid REAL,
            failed_constraints_json TEXT,
            qualification_gaps_json TEXT,
            data_quality_json TEXT,
            market_regime_context_json TEXT,
            source_pass INTEGER,
            snapshot_at TEXT NOT NULL,
            source_market_data_timestamps_json TEXT,
            policy_version TEXT,
            policy_fingerprint TEXT,
            plan_fingerprint TEXT,
            created_at TEXT NOT NULL,
            raw_summary_json TEXT,
            FOREIGN KEY(execution_record_id) REFERENCES research_execution_records(id)
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_run
        ON candidate_snapshots(root_run_id, pass_run_id);

        CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_ticker
        ON candidate_snapshots(ticker, snapshot_at);

        CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_policy
        ON candidate_snapshots(policy_version, policy_fingerprint);

        CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_plan
        ON candidate_snapshots(plan_fingerprint);

        CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_status
        ON candidate_snapshots(actionability_status);

        CREATE TABLE IF NOT EXISTS candidate_forward_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_snapshot_id INTEGER NOT NULL,
            horizon_sessions INTEGER NOT NULL,
            horizon_maturity_date TEXT NOT NULL,
            graded_at TEXT NOT NULL,
            outcome_status TEXT NOT NULL,
            starting_price REAL,
            ending_price REAL,
            forward_return REAL,
            maximum_favorable_excursion REAL,
            maximum_adverse_excursion REAL,
            target_hit INTEGER,
            stop_hit INTEGER,
            first_hit_result TEXT,
            first_hit_timestamp TEXT,
            r_multiple REAL,
            underlying_only INTEGER DEFAULT 0,
            option_price_history_available INTEGER DEFAULT 0,
            ambiguous INTEGER DEFAULT 0,
            warnings_json TEXT,
            errors_json TEXT,
            FOREIGN KEY(candidate_snapshot_id) REFERENCES candidate_snapshots(id),
            UNIQUE(candidate_snapshot_id, horizon_sessions)
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_forward_outcomes_snapshot
        ON candidate_forward_outcomes(candidate_snapshot_id);

        CREATE INDEX IF NOT EXISTS idx_candidate_forward_outcomes_horizon
        ON candidate_forward_outcomes(horizon_sessions, horizon_maturity_date);

        CREATE TABLE IF NOT EXISTS research_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_version TEXT NOT NULL UNIQUE,
            parent_version TEXT,
            status TEXT NOT NULL,
            policy_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            created_by TEXT,
            approved_at TEXT,
            approved_by TEXT,
            approval_reason TEXT,
            evidence_reference TEXT,
            evaluation_reference TEXT,
            immutable_rules_version TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_research_policies_status
        ON research_policies(status);

        CREATE INDEX IF NOT EXISTS idx_research_policies_fingerprint
        ON research_policies(fingerprint);

        CREATE TABLE IF NOT EXISTS policy_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id TEXT NOT NULL UNIQUE,
            proposal_id INTEGER,
            baseline_policy_version TEXT,
            candidate_policy_json TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            evaluation_status TEXT NOT NULL,
            walk_forward_config_json TEXT,
            train_metrics_json TEXT,
            validation_metrics_json TEXT,
            test_metrics_json TEXT,
            comparison_metrics_json TEXT,
            sample_sizes_json TEXT,
            warnings_json TEXT,
            rejection_reasons_json TEXT,
            promotion_eligibility_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_policy_evaluations_candidate
        ON policy_evaluations(candidate_fingerprint);

        CREATE INDEX IF NOT EXISTS idx_policy_evaluations_status
        ON policy_evaluations(evaluation_status);

        CREATE TABLE IF NOT EXISTS policy_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_version TEXT NOT NULL,
            baseline_policy_version TEXT,
            candidate_policy_json TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            evaluation_id TEXT,
            walk_forward_config_json TEXT,
            train_metrics_json TEXT,
            validation_metrics_json TEXT,
            test_metrics_json TEXT,
            comparison_metrics_json TEXT,
            sample_sizes_json TEXT,
            warnings_json TEXT,
            rejection_reasons_json TEXT,
            promotion_eligibility_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by TEXT,
            FOREIGN KEY(evaluation_id) REFERENCES policy_evaluations(evaluation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_policy_proposals_status
        ON policy_proposals(status);

        CREATE INDEX IF NOT EXISTS idx_policy_proposals_baseline
        ON policy_proposals(baseline_policy_version);

        CREATE TABLE IF NOT EXISTS shadow_policy_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_snapshot_id INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            policy_fingerprint TEXT NOT NULL,
            shadow_opportunity_score REAL,
            shadow_rank INTEGER,
            active_rank INTEGER,
            rank_change INTEGER,
            created_at TEXT NOT NULL,
            score_components_json TEXT,
            FOREIGN KEY(candidate_snapshot_id) REFERENCES candidate_snapshots(id),
            UNIQUE(candidate_snapshot_id, policy_fingerprint)
        );

        CREATE INDEX IF NOT EXISTS idx_shadow_policy_scores_policy
        ON shadow_policy_scores(policy_version, policy_fingerprint);
        """,
    },
]


def migration_checksum(sql: str) -> str:
    return hashlib.sha256(str(sql or "").strip().encode("utf-8")).hexdigest()
