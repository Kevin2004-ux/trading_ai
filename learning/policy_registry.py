from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal
import hashlib
import json
import sqlite3

from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.audit_log import append_audit_event
from db.schema_manager import apply_pending_migrations
from ideas.opportunity_ranker import DEFAULT_STOCK_OPPORTUNITY_WEIGHTS, STOCK_OPPORTUNITY_SCORE_VERSION
from ideas.option_opportunity_ranker import DEFAULT_OPTION_OPPORTUNITY_WEIGHTS, OPTION_OPPORTUNITY_SCORE_VERSION
from scanner.scan_profiles import get_default_scan_profiles


LEARNING_VERSION = "research_learning_v1"
RESEARCH_POLICY_SCHEMA_VERSION = "research_policy_v1"
BASELINE_POLICY_VERSION = "research_policy_v1_baseline"
IMMUTABLE_RULES_VERSION = "scan_policy_v1"
POLICY_PROPOSAL_VERSION = "research_policy_proposal_v1"

BLOCKED_POLICY_FIELDS = {
    "paper_trading_only",
    "brokerage_execution",
    "brokerage_execution_enabled",
    "order_placement",
    "place_orders",
    "auto_log",
    "hard_stock_constraints",
    "hard_option_constraints",
    "data_freshness_requirements",
    "market_data_requirements",
    "minimum_strict_risk_reward",
    "minimum_risk_reward",
    "strict_profile_recommendation_thresholds",
    "option_quote_requirements",
    "allow_unquoted_options",
    "iv_greeks_liquidity_spread_fill_gates",
    "portfolio_limits",
    "concentration_limits",
    "circuit_breakers",
    "macro_hard_blocks",
    "trade_logging_eligibility",
    "recommendation_status",
    "passed",
    "bypass_constraints",
}

POLICY_STATUSES = {"baseline", "shadow", "approved", "active", "retired", "rejected"}
SUPPORTED_PROFILES = tuple(sorted(get_default_scan_profiles().keys()))
DEFAULT_STOCK_UNIVERSES = ["large_cap", "active", "tech"]
IMMUTABLE_RULES = [
    "Paper trading only.",
    "Brokerage execution disabled.",
    "No order placement.",
    "Deterministic engine remains source of truth.",
    "Data freshness cannot be disabled.",
    "Essential market-data requirements cannot be disabled.",
    "Strict stock constraints cannot be bypassed.",
    "Portfolio and concentration blocks cannot be overridden.",
    "Circuit-breaker and macro hard blocks cannot be overridden.",
    "Blocked/watchlist candidates cannot be promoted.",
    "Option chain and quote requirements cannot be bypassed.",
    "Option bid/ask, liquidity, IV, Greeks, DTE, spread, breakeven, fill-quality, and risk checks cannot be bypassed.",
    "Logging eligibility cannot be changed by a research policy.",
]


class ResearchPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: Literal["research_policy_v1"] = RESEARCH_POLICY_SCHEMA_VERSION
    stock_opportunity_weights: dict[str, float] = Field(default_factory=dict)
    option_opportunity_weights: dict[str, float] = Field(default_factory=dict)
    profile_preference_weights: dict[str, float] = Field(default_factory=dict)
    default_stock_universes: list[str] = Field(default_factory=list)
    default_option_underlying_limit: int = 5
    default_max_refinement_passes: int = 2
    default_research_preferences: dict[str, bool] = Field(default_factory=dict)
    minimum_display_opportunity_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reject_immutable_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            blocked = sorted(BLOCKED_POLICY_FIELDS.intersection(data.keys()))
            if blocked:
                raise ValueError(f"Research policy cannot contain immutable/safety fields: {', '.join(blocked)}")
        return data

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ResearchPolicyV1":
        if self.default_option_underlying_limit < 1 or self.default_option_underlying_limit > 25:
            raise ValueError("default_option_underlying_limit must be between 1 and 25.")
        if self.default_max_refinement_passes < 1 or self.default_max_refinement_passes > 3:
            raise ValueError("default_max_refinement_passes must be between 1 and 3.")
        if self.minimum_display_opportunity_score is not None and not 0 <= self.minimum_display_opportunity_score <= 100:
            raise ValueError("minimum_display_opportunity_score must be between 0 and 100.")
        _normalize_weights(self.stock_opportunity_weights, set(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS), "stock_opportunity_weights")
        _normalize_weights(self.option_opportunity_weights, set(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS), "option_opportunity_weights")
        _normalize_weights(self.profile_preference_weights, set(SUPPORTED_PROFILES), "profile_preference_weights", allow_empty=True)
        return self


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _load_json(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    for key in (
        "policy_json",
        "promotion_eligibility_json",
        "warnings_json",
        "rejection_reasons_json",
        "candidate_policy_json",
        "walk_forward_config_json",
        "train_metrics_json",
        "validation_metrics_json",
        "test_metrics_json",
        "comparison_metrics_json",
        "sample_sizes_json",
    ):
        if key in payload:
            payload[key] = _load_json(payload[key], {} if key.endswith("_json") else None)
    return payload


def _normalize_weights(weights: dict[str, Any], allowed: set[str], field_name: str, allow_empty: bool = False) -> dict[str, float]:
    if allow_empty and not weights:
        return {}
    if not isinstance(weights, dict) or not weights:
        raise ValueError(f"{field_name} must be a non-empty object.")
    unknown = sorted(str(key) for key in weights if str(key) not in allowed)
    if unknown:
        raise ValueError(f"{field_name} contains unsupported keys: {', '.join(unknown)}")
    normalized: dict[str, float] = {}
    for key, value in weights.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name}.{key} must be numeric.") from None
        if numeric < 0:
            raise ValueError(f"{field_name}.{key} must be non-negative.")
        normalized[str(key)] = numeric
    if sum(normalized.values()) <= 0:
        raise ValueError(f"{field_name} must have positive total weight.")
    return normalized


def canonical_policy_json(policy: dict | ResearchPolicyV1) -> dict:
    model = policy if isinstance(policy, ResearchPolicyV1) else ResearchPolicyV1.model_validate(policy)
    payload = model.model_dump(mode="json")
    payload["stock_opportunity_weights"] = _normalize_weights(
        payload["stock_opportunity_weights"],
        set(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS),
        "stock_opportunity_weights",
    )
    payload["option_opportunity_weights"] = _normalize_weights(
        payload["option_opportunity_weights"],
        set(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS),
        "option_opportunity_weights",
    )
    if payload.get("profile_preference_weights"):
        payload["profile_preference_weights"] = _normalize_weights(
            payload["profile_preference_weights"],
            set(SUPPORTED_PROFILES),
            "profile_preference_weights",
            allow_empty=True,
        )
    payload["default_stock_universes"] = [str(item).strip().lower() for item in payload.get("default_stock_universes", []) if str(item).strip()]
    payload["default_research_preferences"] = {str(key): bool(value) for key, value in payload.get("default_research_preferences", {}).items()}
    return payload


def policy_fingerprint(policy: dict | ResearchPolicyV1) -> str:
    return hashlib.sha256(_json(canonical_policy_json(policy)).encode("utf-8")).hexdigest()


def build_baseline_policy() -> dict:
    profile_count = max(len(SUPPORTED_PROFILES), 1)
    return canonical_policy_json(
        {
            "policy_version": RESEARCH_POLICY_SCHEMA_VERSION,
            "stock_opportunity_weights": deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS),
            "option_opportunity_weights": deepcopy(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS),
            "profile_preference_weights": {profile: 1.0 / profile_count for profile in SUPPORTED_PROFILES},
            "default_stock_universes": DEFAULT_STOCK_UNIVERSES,
            "default_option_underlying_limit": 5,
            "default_max_refinement_passes": 2,
            "default_research_preferences": {
                "include_news": False,
                "include_sec_filings": False,
                "include_earnings_transcripts": False,
                "include_short_interest": True,
            },
            "minimum_display_opportunity_score": None,
            "metadata": {
                "stock_opportunity_score_version": STOCK_OPPORTUNITY_SCORE_VERSION,
                "option_opportunity_score_version": OPTION_OPPORTUNITY_SCORE_VERSION,
                "baseline_reproduces_current_defaults": True,
            },
        }
    )


def validate_research_policy(policy: dict) -> dict:
    try:
        canonical = canonical_policy_json(policy)
        return {
            "ok": True,
            "policy": canonical,
            "fingerprint": policy_fingerprint(canonical),
            "errors": [],
            "warnings": [],
        }
    except Exception as exc:
        return {"ok": False, "policy": {}, "fingerprint": "", "errors": [str(exc)], "warnings": []}


def seed_baseline_policy(db_path: str = "strategy_library.db") -> dict:
    try:
        apply_pending_migrations(db_path)
        policy = build_baseline_policy()
        fingerprint = policy_fingerprint(policy)
        now = _now_iso()
        with _connect(db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM research_policies WHERE policy_version = ? OR fingerprint = ?",
                (BASELINE_POLICY_VERSION, fingerprint),
            ).fetchone()
            active = conn.execute("SELECT * FROM research_policies WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
            if existing:
                row = existing
                if row["status"] != "active" and not active:
                    conn.execute("UPDATE research_policies SET status = 'active' WHERE id = ?", (row["id"],))
                    row = conn.execute("SELECT * FROM research_policies WHERE id = ?", (row["id"],)).fetchone()
            elif not active:
                cursor = conn.execute(
                    """
                    INSERT INTO research_policies (
                        policy_version, parent_version, status, policy_json, fingerprint,
                        created_at, created_by, evidence_reference, immutable_rules_version
                    ) VALUES (?, NULL, 'active', ?, ?, ?, 'system', ?, ?)
                    """,
                    (
                        BASELINE_POLICY_VERSION,
                        _json(policy),
                        fingerprint,
                        now,
                        "baseline_seed",
                        IMMUTABLE_RULES_VERSION,
                    ),
                )
                row = conn.execute("SELECT * FROM research_policies WHERE id = ?", (cursor.lastrowid,)).fetchone()
            else:
                row = active
        return {"ok": True, "policy": _row_to_dict(row), "seeded": bool(not existing and not active), "errors": []}
    except sqlite3.Error as exc:
        return {"ok": False, "policy": None, "seeded": False, "errors": [str(exc)]}


def get_active_policy(db_path: str = "strategy_library.db") -> dict:
    seeded = seed_baseline_policy(db_path)
    if not seeded.get("ok"):
        return {"ok": False, "policy": None, "active_policy_version": "", "active_policy_fingerprint": "", "errors": seeded.get("errors", [])}
    try:
        with _connect(db_path) as conn:
            row = conn.execute("SELECT * FROM research_policies WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        policy = _row_to_dict(row)
        return {
            "ok": policy is not None,
            "policy": policy,
            "active_policy_version": policy.get("policy_version") if policy else "",
            "active_policy_fingerprint": policy.get("fingerprint") if policy else "",
            "errors": [] if policy else ["No active research policy found."],
        }
    except sqlite3.Error as exc:
        return {"ok": False, "policy": None, "active_policy_version": "", "active_policy_fingerprint": "", "errors": [str(exc)]}


def list_policies(db_path: str = "strategy_library.db", include_policy_json: bool = True) -> dict:
    try:
        seed_baseline_policy(db_path)
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM research_policies ORDER BY id ASC").fetchall()
        policies = [_row_to_dict(row) for row in rows]
        if not include_policy_json:
            for policy in policies:
                policy.pop("policy_json", None)
        return {"ok": True, "policies": policies, "count": len(policies), "errors": []}
    except sqlite3.Error as exc:
        return {"ok": False, "policies": [], "count": 0, "errors": [str(exc)]}


def get_shadow_policies(db_path: str = "strategy_library.db", limit: int = 5) -> dict:
    try:
        seed_baseline_policy(db_path)
        safe_limit = max(0, min(int(limit), 10))
        with _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM research_policies WHERE status = 'shadow' ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return {"ok": True, "policies": [_row_to_dict(row) for row in rows], "count": len(rows), "errors": []}
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return {"ok": False, "policies": [], "count": 0, "errors": [str(exc)]}


def active_policy_defaults(db_path: str = "strategy_library.db") -> dict:
    active = get_active_policy(db_path)
    policy_row = active.get("policy") or {}
    policy = policy_row.get("policy_json") or build_baseline_policy()
    return {
        "ok": bool(active.get("ok")),
        "active_policy_version": active.get("active_policy_version") or BASELINE_POLICY_VERSION,
        "active_policy_fingerprint": active.get("active_policy_fingerprint") or policy_fingerprint(policy),
        "policy": policy,
        "opportunity_ranker": {"weights": policy.get("stock_opportunity_weights", DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)},
        "option_opportunity_ranker": {"weights": policy.get("option_opportunity_weights", DEFAULT_OPTION_OPPORTUNITY_WEIGHTS)},
        "default_stock_universes": policy.get("default_stock_universes", []),
        "default_max_refinement_passes": policy.get("default_max_refinement_passes", 2),
        "default_option_underlying_limit": policy.get("default_option_underlying_limit", 5),
        "errors": active.get("errors", []),
    }


def insert_shadow_policy(
    policy: dict,
    baseline_policy_version: str,
    created_by: str,
    db_path: str = "strategy_library.db",
) -> dict:
    validation = validate_research_policy(policy)
    if not validation.get("ok"):
        return validation
    try:
        apply_pending_migrations(db_path)
        now = _now_iso()
        fingerprint = validation["fingerprint"]
        policy_payload = validation["policy"]
        version = f"research_policy_v1_shadow_{fingerprint[:12]}"
        with _connect(db_path) as conn:
            row = conn.execute("SELECT * FROM research_policies WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if row:
                return {"ok": True, "policy": _row_to_dict(row), "duplicate": True, "errors": []}
            cursor = conn.execute(
                """
                INSERT INTO research_policies (
                    policy_version, parent_version, status, policy_json, fingerprint,
                    created_at, created_by, immutable_rules_version
                ) VALUES (?, ?, 'shadow', ?, ?, ?, ?, ?)
                """,
                (version, baseline_policy_version, _json(policy_payload), fingerprint, now, created_by, IMMUTABLE_RULES_VERSION),
            )
            row = conn.execute("SELECT * FROM research_policies WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return {"ok": True, "policy": _row_to_dict(row), "duplicate": False, "errors": []}
    except sqlite3.Error as exc:
        return {"ok": False, "policy": None, "duplicate": False, "errors": [str(exc)]}


def promote_policy_proposal(
    proposal_id: int,
    approved_by: str,
    approval_reason: str,
    expected_current_policy_version: str,
    confirm: bool,
    db_path: str = "strategy_library.db",
) -> dict:
    errors: list[str] = []
    if not confirm:
        errors.append("confirm must be true for manual promotion.")
    if not str(approved_by or "").strip():
        errors.append("approved_by is required.")
    if not str(approval_reason or "").strip():
        errors.append("approval_reason is required.")
    if errors:
        return {"ok": False, "promoted": False, "errors": errors, "warnings": []}
    try:
        seed_baseline_policy(db_path)
        now = _now_iso()
        with _connect(db_path) as conn:
            current = conn.execute("SELECT * FROM research_policies WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
            if not current or current["policy_version"] != expected_current_policy_version:
                return {"ok": False, "promoted": False, "errors": ["expected_current_policy_version does not match the active policy."], "warnings": []}
            proposal = conn.execute("SELECT * FROM policy_proposals WHERE id = ?", (proposal_id,)).fetchone()
            if not proposal:
                return {"ok": False, "promoted": False, "errors": [f"Policy proposal not found: {proposal_id}"], "warnings": []}
            proposal_payload = _row_to_dict(proposal)
            eligibility = proposal_payload.get("promotion_eligibility_json") or {}
            if not eligibility.get("promotion_eligible"):
                return {"ok": False, "promoted": False, "errors": ["Proposal is not promotion-eligible."], "warnings": eligibility.get("blocking_reasons", [])}
            if proposal_payload.get("status") not in {"shadow", "approved"}:
                return {"ok": False, "promoted": False, "errors": ["Proposal must be in shadow or approved status before promotion."], "warnings": []}
            version = f"research_policy_v1_active_{proposal_payload['candidate_fingerprint'][:12]}"
            conn.execute("UPDATE research_policies SET status = 'retired' WHERE status = 'active'")
            conn.execute(
                """
                INSERT INTO research_policies (
                    policy_version, parent_version, status, policy_json, fingerprint, created_at,
                    created_by, approved_at, approved_by, approval_reason, evaluation_reference,
                    evidence_reference, immutable_rules_version
                ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    policy_version = excluded.policy_version,
                    parent_version = excluded.parent_version,
                    status = 'active',
                    policy_json = excluded.policy_json,
                    approved_at = excluded.approved_at,
                    approved_by = excluded.approved_by,
                    approval_reason = excluded.approval_reason,
                    evaluation_reference = excluded.evaluation_reference,
                    evidence_reference = excluded.evidence_reference,
                    immutable_rules_version = excluded.immutable_rules_version
                """,
                (
                    version,
                    current["policy_version"],
                    _json(proposal_payload.get("candidate_policy_json")),
                    proposal_payload["candidate_fingerprint"],
                    now,
                    proposal_payload.get("created_by") or "user",
                    now,
                    approved_by,
                    approval_reason,
                    proposal_payload.get("evaluation_id"),
                    f"policy_proposal:{proposal_id}",
                    IMMUTABLE_RULES_VERSION,
                ),
            )
            conn.execute("UPDATE policy_proposals SET status = 'approved', updated_at = ? WHERE id = ?", (now, proposal_id))
            active = conn.execute("SELECT * FROM research_policies WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        audit = append_audit_event(
            db_path,
            "research_policy_promoted",
            {
                "proposal_id": proposal_id,
                "approved_by": approved_by,
                "approval_reason": approval_reason,
                "old_policy_version": expected_current_policy_version,
                "new_policy_version": _row_to_dict(active).get("policy_version") if active else None,
                "immutable_rules": IMMUTABLE_RULES,
            },
            entity_type="research_policy",
            entity_id=str(proposal_id),
        )
        return {"ok": True, "promoted": True, "active_policy": _row_to_dict(active), "audit_event": audit, "errors": [], "warnings": []}
    except sqlite3.Error as exc:
        return {"ok": False, "promoted": False, "errors": [str(exc)], "warnings": []}
