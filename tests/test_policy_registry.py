import sqlite3

import pytest

from db.schema_manager import apply_pending_migrations
from ideas.opportunity_ranker import DEFAULT_STOCK_OPPORTUNITY_WEIGHTS
from ideas.option_opportunity_ranker import DEFAULT_OPTION_OPPORTUNITY_WEIGHTS
from learning import (
    BASELINE_POLICY_VERSION,
    build_baseline_policy,
    get_active_policy,
    list_policies,
    policy_fingerprint,
    seed_baseline_policy,
    validate_research_policy,
)


def test_baseline_policy_seeding_reproduces_current_defaults(tmp_path):
    db_path = str(tmp_path / "learning.db")

    result = seed_baseline_policy(db_path)
    active = get_active_policy(db_path)
    policies = list_policies(db_path)
    baseline = build_baseline_policy()

    assert result["ok"] is True
    assert active["active_policy_version"] == BASELINE_POLICY_VERSION
    assert active["active_policy_fingerprint"] == policy_fingerprint(baseline)
    assert active["policy"]["policy_json"]["stock_opportunity_weights"] == DEFAULT_STOCK_OPPORTUNITY_WEIGHTS
    assert active["policy"]["policy_json"]["option_opportunity_weights"] == DEFAULT_OPTION_OPPORTUNITY_WEIGHTS
    assert active["policy"]["policy_json"]["metadata"]["baseline_reproduces_current_defaults"] is True
    assert policies["count"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("paper_trading_only", False),
        ("brokerage_execution", True),
        ("bypass_constraints", True),
        ("minimum_risk_reward", 0.5),
        ("allow_unquoted_options", True),
        ("auto_log", True),
    ],
)
def test_research_policy_rejects_immutable_safety_fields(field, value):
    policy = build_baseline_policy()
    policy[field] = value

    result = validate_research_policy(policy)

    assert result["ok"] is False
    assert field in result["errors"][0]


def test_migration_adds_learning_tables(tmp_path):
    db_path = str(tmp_path / "migrations.db")

    result = apply_pending_migrations(db_path)

    assert result["ok"] is True
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "research_execution_records",
        "candidate_snapshots",
        "candidate_forward_outcomes",
        "research_policies",
        "policy_evaluations",
        "policy_proposals",
        "shadow_policy_scores",
    }.issubset(tables)
