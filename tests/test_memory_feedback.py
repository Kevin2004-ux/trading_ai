from memory.memory_feedback import evaluate_annotation_feedback


def test_no_annotations_returns_unknown_feedback():
    result = evaluate_annotation_feedback({"ticker": "AAPL"}, {"ok": True, "total_annotations": 0})

    assert result["feedback_status"] == "unknown"
    assert result["score_adjustment"] == 0.0


def test_repeated_negative_annotations_reduce_score_and_risk():
    result = evaluate_annotation_feedback(
        {"ticker": "AAPL"},
        {"ok": True, "total_annotations": 3, "positive_count": 0, "negative_count": 3, "blocking_count": 0, "average_rating": -1.5},
    )

    assert result["feedback_status"] == "caution"
    assert result["score_adjustment"] < 0
    assert result["risk_multiplier"] < 1.0


def test_repeated_positive_annotations_add_small_support():
    result = evaluate_annotation_feedback(
        {"ticker": "AAPL"},
        {"ok": True, "total_annotations": 3, "positive_count": 3, "negative_count": 0, "blocking_count": 0, "average_rating": 2},
    )

    assert result["feedback_status"] == "supportive"
    assert result["score_adjustment"] > 0
    assert result["risk_multiplier"] == 1.0


def test_explicit_blocking_annotation_blocks_matching_setup():
    result = evaluate_annotation_feedback(
        {"ticker": "AAPL", "setup_type": "relative_strength"},
        {"ok": True, "total_annotations": 1, "positive_count": 0, "negative_count": 0, "blocking_count": 1, "average_rating": None},
    )

    assert result["feedback_status"] == "blocking"
    assert result["risk_multiplier"] == 0.0
