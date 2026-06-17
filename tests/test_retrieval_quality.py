from datetime import datetime, timedelta, timezone

from memory.retrieval_quality import evaluate_retrieval_quality


def _match(score=0.9, days_old=5, outcome="win", verified=True, source="db1"):
    return {
        "memory_id": f"m-{score}",
        "score": score,
        "metadata": {
            "created_at": (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(),
            "outcome": outcome,
            "outcome_verified": verified,
            "source_db_path": source,
        },
    }


def test_no_retrieval_results_fails_quality_gate():
    result = evaluate_retrieval_quality({"ok": True, "matches": []})

    assert result["quality_status"] == "fail"
    assert result["usable_for_decision_support"] is False
    assert result["usable_for_explanation"] is False


def test_low_similarity_fails_decision_support():
    result = evaluate_retrieval_quality({"ok": True, "matches": [_match(score=0.6)]})

    assert result["quality_status"] == "fail"
    assert result["usable_for_decision_support"] is False


def test_medium_similarity_is_explanation_only():
    result = evaluate_retrieval_quality({"ok": True, "matches": [_match(score=0.78)]})

    assert result["quality_status"] == "warn"
    assert result["usable_for_explanation"] is True
    assert result["usable_for_decision_support"] is False


def test_high_similarity_passes_if_fresh_and_verified():
    result = evaluate_retrieval_quality({"ok": True, "matches": [_match(score=0.91), _match(score=0.85, source="db2")]})

    assert result["quality_status"] == "pass"
    assert result["usable_for_decision_support"] is True
    assert result["top_score"] == 0.91
    assert result["source_diversity"] == 2


def test_stale_memory_warns_and_blocks_decision_support():
    result = evaluate_retrieval_quality({"ok": True, "matches": [_match(score=0.91, days_old=500)]}, config={"MEMORY_MAX_AGE_DAYS": 365})

    assert result["quality_status"] == "warn"
    assert result["usable_for_decision_support"] is False
    assert any("above max age" in warning for warning in result["warnings"])


def test_contradictory_memory_blocks_decision_support():
    result = evaluate_retrieval_quality(
        {"ok": True, "matches": [_match(score=0.91, outcome="win"), _match(score=0.9, outcome="loss"), _match(score=0.88, outcome="loss")]}
    )

    assert result["quality_status"] == "warn"
    assert result["contradiction_risk"] == "high"
    assert result["usable_for_decision_support"] is False


def test_unverified_memory_is_explanation_only_when_verified_required():
    result = evaluate_retrieval_quality({"ok": True, "matches": [_match(score=0.91, outcome="unknown", verified=False)]})

    assert result["quality_status"] == "warn"
    assert result["usable_for_explanation"] is True
    assert result["usable_for_decision_support"] is False
