from __future__ import annotations

import sqlite3

from db.schema_manager import apply_pending_migrations

from .policy_proposals import legacy_optimizer_diagnostics, list_policy_proposals
from .policy_registry import LEARNING_VERSION, active_policy_defaults, get_shadow_policies, list_policies
from .run_recorder import get_snapshot_counts


MINIMUM_SAMPLE_REQUIREMENTS = {
    "overall": 90,
    "train": 30,
    "validation": 30,
    "test": 30,
}


def get_learning_status(db_path: str = "strategy_library.db") -> dict:
    response = {
        "ok": True,
        "learning_version": LEARNING_VERSION,
        "status": "collecting_data",
        "active_policy_version": "",
        "candidate_snapshot_count": 0,
        "mature_outcome_count": 0,
        "pending_outcome_count": 0,
        "exact_option_outcome_count": 0,
        "underlying_only_option_outcome_count": 0,
        "minimum_sample_requirements": MINIMUM_SAMPLE_REQUIREMENTS,
        "walk_forward_ready": False,
        "promotion_ready": False,
        "active_policy": {},
        "shadow_policies": [],
        "policies": [],
        "latest_evaluation": None,
        "legacy_optimizer_diagnostics": legacy_optimizer_diagnostics(),
        "warnings": [],
        "errors": [],
    }
    try:
        apply_pending_migrations(db_path)
        active = active_policy_defaults(db_path)
        counts = get_snapshot_counts(db_path)
        policies = list_policies(db_path, include_policy_json=False)
        shadows = get_shadow_policies(db_path)
        proposals = list_policy_proposals(db_path, limit=1)
        with sqlite3.connect(db_path) as conn:
            exact_options = conn.execute(
                "SELECT COUNT(*) FROM candidate_forward_outcomes WHERE option_price_history_available = 1"
            ).fetchone()[0]
            underlying_only = conn.execute(
                "SELECT COUNT(*) FROM candidate_forward_outcomes WHERE underlying_only = 1"
            ).fetchone()[0]
        response["active_policy_version"] = active.get("active_policy_version", "")
        response["active_policy"] = active.get("policy", {})
        response["candidate_snapshot_count"] = counts.get("candidate_snapshot_count", 0)
        response["mature_outcome_count"] = counts.get("mature_outcome_count", 0)
        response["pending_outcome_count"] = counts.get("pending_outcome_count", 0)
        response["exact_option_outcome_count"] = exact_options
        response["underlying_only_option_outcome_count"] = underlying_only
        response["policies"] = policies.get("policies", [])
        response["shadow_policies"] = shadows.get("policies", [])
        response["latest_evaluation"] = proposals.get("proposals", [None])[0] if proposals.get("proposals") else None
        response["walk_forward_ready"] = response["mature_outcome_count"] >= response["minimum_sample_requirements"]["overall"]
        response["promotion_ready"] = False
        if response["walk_forward_ready"]:
            response["status"] = "ready"
        elif response["candidate_snapshot_count"] > 0:
            response["status"] = "collecting_data"
            response["warnings"].append("Learning is collecting point-in-time snapshots; promotion is not ready.")
        else:
            response["status"] = "insufficient_data"
            response["warnings"].append("No candidate snapshots have matured into learning outcomes yet.")
        response["errors"].extend(active.get("errors", []))
        response["ok"] = not response["errors"]
        return response
    except Exception as exc:
        response["ok"] = False
        response["status"] = "degraded"
        response["errors"].append(str(exc))
        return response
