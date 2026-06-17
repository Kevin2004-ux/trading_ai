from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


DEFAULT_MIN_SIMILARITY = 0.82
DEFAULT_EXPLANATION_MIN_SIMILARITY = 0.75
DEFAULT_MAX_AGE_DAYS = 365


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_float(config: dict | None, *names: str, default: float) -> float:
    supplied = config if isinstance(config, dict) else {}
    for name in names:
        if name in supplied:
            value = _safe_float(supplied.get(name))
            if value is not None:
                return value
        value = _safe_float(os.getenv(name))
        if value is not None:
            return value
    return default


def _config_int(config: dict | None, *names: str, default: int) -> int:
    supplied = config if isinstance(config, dict) else {}
    for name in names:
        if name in supplied:
            return _safe_int(supplied.get(name), default)
        if os.getenv(name) is not None:
            return _safe_int(os.getenv(name), default)
    return default


def _config_bool(config: dict | None, *names: str, default: bool = False) -> bool:
    supplied = config if isinstance(config, dict) else {}
    for name in names:
        if name in supplied:
            return _safe_bool(supplied.get(name), default)
        if os.getenv(name) is not None:
            return _safe_bool(os.getenv(name), default)
    return default


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _match_metadata(match: dict) -> dict:
    if not isinstance(match, dict):
        return {}
    metadata = match.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_days(matches: list[dict]) -> float | None:
    ages: list[float] = []
    now = datetime.now(timezone.utc)
    for match in matches:
        metadata = _match_metadata(match)
        created_at = _parse_datetime(metadata.get("created_at") or match.get("created_at"))
        if created_at is not None:
            ages.append((now - created_at).total_seconds() / 86400.0)
    if not ages:
        return None
    return round(min(ages), 2)


def _source_diversity(matches: list[dict]) -> int:
    sources = set()
    for match in matches:
        metadata = _match_metadata(match)
        source = metadata.get("source_db_path") or metadata.get("source") or match.get("source") or metadata.get("item_type")
        if source:
            sources.add(str(source))
    return len(sources)


def _outcome_bucket(match: dict) -> str:
    metadata = _match_metadata(match)
    outcome = str(metadata.get("outcome") or match.get("outcome") or "").strip().lower()
    if outcome in {"win", "winner", "positive"}:
        return "positive"
    if outcome in {"loss", "loser", "negative", "failed"}:
        return "negative"
    return "unknown"


def _contradiction_risk(matches: list[dict], query_context: dict | None) -> str:
    if not matches:
        return "unknown"
    positive = sum(1 for match in matches if _outcome_bucket(match) == "positive")
    negative = sum(1 for match in matches if _outcome_bucket(match) == "negative")
    if positive and negative:
        return "high"

    query_direction = str((query_context or {}).get("direction") or "").lower()
    directions = {
        str(_match_metadata(match).get("direction") or match.get("direction") or "").lower()
        for match in matches
        if str(_match_metadata(match).get("direction") or match.get("direction") or "").strip()
    }
    if query_direction and directions and any(direction and direction != query_direction for direction in directions):
        return "medium"
    return "low"


def _verified_outcome(match: dict) -> bool:
    metadata = _match_metadata(match)
    verified = metadata.get("outcome_verified")
    if verified is None:
        verified = metadata.get("verified_outcome")
    if verified is not None:
        return _safe_bool(verified, False)
    outcome = str(metadata.get("outcome") or match.get("outcome") or "").strip().lower()
    return outcome in {"win", "loss", "expired", "manual_review"}


def evaluate_retrieval_quality(
    retrieval_result: dict,
    query_context: dict | None = None,
    config: dict | None = None,
) -> dict:
    min_similarity = _config_float(config, "MEMORY_MIN_SIMILARITY", "memory_min_similarity", default=DEFAULT_MIN_SIMILARITY)
    explanation_min = _config_float(config, "MEMORY_EXPLANATION_MIN_SIMILARITY", "memory_explanation_min_similarity", default=DEFAULT_EXPLANATION_MIN_SIMILARITY)
    max_age_days = _config_int(config, "MEMORY_MAX_AGE_DAYS", "memory_max_age_days", default=DEFAULT_MAX_AGE_DAYS)
    require_verified = _config_bool(config, "MEMORY_REQUIRE_VERIFIED_OUTCOMES", "memory_require_verified_outcomes", default=True)

    warnings: list[str] = []
    errors: list[str] = []
    matches = _as_list((retrieval_result or {}).get("matches") if isinstance(retrieval_result, dict) else [])
    scores = [_safe_float(match.get("score")) for match in matches if isinstance(match, dict)]
    scores = [score for score in scores if score is not None]
    result_count = len(matches)
    top_score = max(scores) if scores else None
    avg_score = round(sum(scores) / len(scores), 4) if scores else None
    freshness_days = _freshness_days(matches)
    source_diversity = _source_diversity(matches)
    contradiction_risk = _contradiction_risk(matches, query_context)

    if not isinstance(retrieval_result, dict) or not retrieval_result.get("ok"):
        errors.append((retrieval_result or {}).get("error") if isinstance(retrieval_result, dict) else "Retrieval result is malformed.")
    if result_count == 0:
        errors.append("No memory results were returned.")
    if top_score is None:
        errors.append("No similarity scores were returned.")
    elif top_score < explanation_min:
        errors.append(f"Top similarity {round(top_score, 4)} is below explanation threshold {explanation_min}.")
    elif top_score < min_similarity:
        warnings.append(f"Top similarity {round(top_score, 4)} is below decision-support threshold {min_similarity}; explanation-only.")

    if freshness_days is None:
        warnings.append("Memory freshness could not be determined.")
    elif freshness_days > max_age_days:
        warnings.append(f"Most recent memory is {round(freshness_days, 2)} days old, above max age {max_age_days}.")

    if contradiction_risk == "high":
        warnings.append("Retrieved memories contain contradictory prior outcomes or directions.")
    elif contradiction_risk == "medium":
        warnings.append("Retrieved memories contain mixed context; use cautiously.")

    if require_verified and matches:
        unverified_count = sum(1 for match in matches if isinstance(match, dict) and not _verified_outcome(match))
        if unverified_count == len(matches):
            warnings.append("Retrieved memories do not have verified outcomes; explanation-only.")
        elif unverified_count:
            warnings.append(f"{unverified_count} retrieved memories lack verified outcomes.")

    usable_for_explanation = bool(result_count and top_score is not None and top_score >= explanation_min and not errors)
    usable_for_decision_support = bool(
        usable_for_explanation
        and top_score is not None
        and top_score >= min_similarity
        and contradiction_risk != "high"
        and (freshness_days is None or freshness_days <= max_age_days)
        and not (require_verified and matches and all(not _verified_outcome(match) for match in matches if isinstance(match, dict)))
    )

    if errors:
        quality_status = "fail"
    elif usable_for_decision_support:
        quality_status = "pass"
    else:
        quality_status = "warn"

    return {
        "ok": True,
        "quality_status": quality_status,
        "usable_for_decision_support": usable_for_decision_support,
        "usable_for_explanation": usable_for_explanation,
        "top_score": round(top_score, 4) if top_score is not None else None,
        "avg_score": avg_score,
        "result_count": result_count,
        "freshness_days": freshness_days,
        "source_diversity": source_diversity,
        "contradiction_risk": contradiction_risk,
        "warnings": [warning for warning in warnings if warning],
        "errors": [error for error in errors if error],
    }
