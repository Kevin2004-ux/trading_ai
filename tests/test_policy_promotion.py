import json
import sqlite3

from db.audit_log import list_audit_events
from db.schema_manager import apply_pending_migrations
from learning import (
    active_policy_defaults,
    build_baseline_policy,
    create_policy_proposal,
    promote_policy_proposal,
    record_shadow_policy_scores,
    seed_baseline_policy,
)


def test_create_policy_proposal_starts_shadow_and_does_not_promote(tmp_path):
    db_path = str(tmp_path / "proposal.db")
    policy = build_baseline_policy()
    policy["minimum_display_opportunity_score"] = 60

    result = create_policy_proposal(policy, created_by="user", db_path=db_path)
    active = active_policy_defaults(db_path)

    assert result["ok"] is True
    assert result["proposal"]["status"] == "shadow"
    assert result["evaluation"]["status"] in {"insufficient_data", "completed"}
    assert result["proposal"]["promotion_eligibility_json"]["promotion_eligible"] is False
    assert active["active_policy_version"] == "research_policy_v1_baseline"


def test_manual_promotion_requires_confirmation_and_metadata(tmp_path):
    db_path = str(tmp_path / "manual.db")
    seed_baseline_policy(db_path)

    assert promote_policy_proposal(1, "human", "because", "research_policy_v1_baseline", False, db_path)["ok"] is False
    assert promote_policy_proposal(1, "", "because", "research_policy_v1_baseline", True, db_path)["ok"] is False
    assert promote_policy_proposal(1, "human", "", "research_policy_v1_baseline", True, db_path)["ok"] is False


def test_stale_expected_policy_version_fails(tmp_path):
    db_path = str(tmp_path / "stale.db")
    seed_baseline_policy(db_path)

    result = promote_policy_proposal(1, "human", "approved", "old_version", True, db_path)

    assert result["ok"] is False
    assert "expected_current_policy_version" in result["errors"][0]


def test_ineligible_proposal_cannot_promote(tmp_path):
    db_path = str(tmp_path / "ineligible.db")
    proposal = create_policy_proposal(build_baseline_policy(), created_by="user", db_path=db_path)

    result = promote_policy_proposal(
        proposal["proposal"]["id"],
        approved_by="human",
        approval_reason="not enough evidence",
        expected_current_policy_version="research_policy_v1_baseline",
        confirm=True,
        db_path=db_path,
    )

    assert result["ok"] is False
    assert "not promotion-eligible" in result["errors"][0]


def test_eligible_mocked_proposal_promotes_and_retires_prior_active_policy(tmp_path):
    db_path = str(tmp_path / "eligible.db")
    apply_pending_migrations(db_path)
    seed_baseline_policy(db_path)
    policy = build_baseline_policy()
    policy["minimum_display_opportunity_score"] = 55
    fingerprint = __import__("learning").policy_fingerprint(policy)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO policy_proposals (
                proposal_version, baseline_policy_version, candidate_policy_json,
                candidate_fingerprint, status, promotion_eligibility_json,
                created_at, updated_at, created_by
            ) VALUES ('research_policy_proposal_v1', 'research_policy_v1_baseline', ?, ?, 'shadow', ?, '2026-06-22T00:00:00+00:00', '2026-06-22T00:00:00+00:00', 'user')
            """,
            (
                json.dumps(policy),
                fingerprint,
                json.dumps({"promotion_eligible": True, "blocking_reasons": []}),
            ),
        )
        proposal_id = cursor.lastrowid

    result = promote_policy_proposal(
        proposal_id,
        approved_by="human",
        approval_reason="mocked evidence requirements satisfied",
        expected_current_policy_version="research_policy_v1_baseline",
        confirm=True,
        db_path=db_path,
    )
    audit = list_audit_events(db_path, limit=10)

    assert result["ok"] is True
    assert result["promoted"] is True
    with sqlite3.connect(db_path) as conn:
        statuses = conn.execute("SELECT policy_version, status FROM research_policies").fetchall()
    assert any(row[1] == "retired" for row in statuses)
    assert any(row[1] == "active" and row[0] != "research_policy_v1_baseline" for row in statuses)
    assert any(event["event_type"] == "research_policy_promoted" for event in audit["events"])


def test_shadow_policy_scores_do_not_change_visible_ranking_or_log_trades(tmp_path):
    db_path = str(tmp_path / "shadow.db")
    proposal = create_policy_proposal(build_baseline_policy(), created_by="user", db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO candidate_snapshots (
                root_run_id, ticker, asset_type, actionability_status, opportunity_score,
                opportunity_components_json, snapshot_at, created_at, policy_version, plan_fingerprint
            ) VALUES ('run', 'AAPL', 'stock', 'blocked', 50, ?, '2026-06-22', '2026-06-22', 'research_policy_v1_baseline', 'plan')
            """,
            (json.dumps({"engine_core": {"score": 80, "available": True}}),),
        )

    result = record_shadow_policy_scores(db_path)

    assert result["ok"] is True
    assert result["provider_calls_made"] == 0
    assert result["trade_logs_created"] == 0
    assert result["visible_ranking_changed"] is False
