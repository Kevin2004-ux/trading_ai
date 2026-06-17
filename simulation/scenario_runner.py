from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from simulation.scenario_definitions import get_stress_scenario, list_stress_scenarios
from simulation.stress_engine import apply_stress_scenario


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_trading_result() -> dict:
    return {
        "ok": True,
        "mode": "paper_trading",
        "summary": {"selected_count": 1, "logged_count": 0},
        "decision_result": {
            "final_recommendations": [
                {
                    "ticker": "AAPL",
                    "asset_type": "stock",
                    "direction": "long",
                    "entry_price": 100.0,
                    "target_price": 112.0,
                    "stop_loss": 94.0,
                    "risk_reward": 2.0,
                    "recommendation_status": "recommendable",
                    "passed": True,
                }
            ]
        },
        "warnings": [],
        "errors": [],
    }


def _resolve_scenarios(scenarios: list[str | dict] | None) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    if scenarios is None:
        listed = list_stress_scenarios()
        return list(listed.get("scenarios", [])), errors

    resolved: list[dict] = []
    for item in scenarios:
        if isinstance(item, dict):
            resolved.append(deepcopy(item))
            continue
        lookup = get_stress_scenario(str(item))
        if lookup.get("ok") and isinstance(lookup.get("scenario"), dict):
            resolved.append(lookup["scenario"])
        else:
            errors.extend(str(error) for error in lookup.get("errors", []))
    return resolved, errors


def _expected_result(stressed: dict, scenario: dict) -> dict:
    expected = scenario.get("expected_behavior") if isinstance(scenario.get("expected_behavior"), dict) else {}
    decision = stressed.get("decision") if isinstance(stressed.get("decision"), dict) else {}
    risk_impact = stressed.get("risk_impact") if isinstance(stressed.get("risk_impact"), dict) else {}
    warnings = stressed.get("warnings") if isinstance(stressed.get("warnings"), list) else []
    affected_components = scenario.get("affected_components") if isinstance(scenario.get("affected_components"), list) else []
    severity = str(scenario.get("severity", "")).lower()
    raw_multiplier = risk_impact.get("risk_multiplier")
    risk_multiplier = 1.0 if raw_multiplier is None else float(raw_multiplier)
    option_only_high_alert = severity == "high" and affected_components and all(
        str(component) in {"options", "iv_rank", "fill_quality"} for component in affected_components
    )

    checks = {
        "returns_json": isinstance(stressed, dict) and bool(stressed.get("ok")),
        "blocks_new_trades": decision.get("new_trades_allowed") is False,
        "reduces_risk": risk_multiplier < 1.0,
        "creates_alert": severity == "extreme" or (severity == "high" and not option_only_high_alert),
    }
    failures: list[str] = []
    if bool(expected.get("should_return_json", True)) != checks["returns_json"]:
        failures.append("Expected structured JSON response behavior did not match.")
    if bool(expected.get("should_block_new_trades", False)) != checks["blocks_new_trades"]:
        failures.append("Expected block-new-trades behavior did not match.")
    if bool(expected.get("should_reduce_risk", False)) != checks["reduces_risk"]:
        failures.append("Expected risk-reduction behavior did not match.")
    if bool(expected.get("should_create_alert", False)) != checks["creates_alert"]:
        failures.append("Expected alert behavior did not match.")
    return {
        "passed": not failures,
        "expected_behavior": expected,
        "observed_behavior": checks,
        "failures": failures,
    }


def run_scenario_suite(
    trading_result: dict | None = None,
    scenarios: list[str | dict] | None = None,
    config: dict | None = None,
) -> dict:
    base = deepcopy(trading_result) if isinstance(trading_result, dict) else _sample_trading_result()
    resolved, errors = _resolve_scenarios(scenarios)
    results: list[dict] = []
    warnings: list[str] = []

    for scenario in resolved:
        stressed = apply_stress_scenario(base, scenario, config=config)
        expectation = _expected_result(stressed, scenario)
        if not expectation["passed"]:
            warnings.extend(expectation["failures"])
        results.append(
            {
                "scenario_name": scenario.get("scenario_name"),
                "severity": scenario.get("severity"),
                "passed_expected_behavior": expectation["passed"],
                "expected_behavior": expectation["expected_behavior"],
                "observed_behavior": expectation["observed_behavior"],
                "stress_result": stressed,
                "failures": expectation["failures"],
            }
        )

    failed = [item for item in results if not item.get("passed_expected_behavior")]
    blocked = [
        item
        for item in results
        if (item.get("stress_result") or {}).get("decision", {}).get("new_trades_allowed") is False
    ]
    reduced = [
        item
        for item in results
        if (
            (
                ((item.get("stress_result") or {}).get("risk_impact") or {}).get("risk_multiplier", 1.0)
                if ((item.get("stress_result") or {}).get("risk_impact") or {}).get("risk_multiplier") is not None
                else 1.0
            )
            < 1.0
        )
    ]
    critical_findings = [
        {
            "scenario_name": item.get("scenario_name"),
            "severity": item.get("severity"),
            "message": "Scenario blocked new simulated trades or failed expected behavior.",
        }
        for item in results
        if item.get("severity") == "extreme" or not item.get("passed_expected_behavior")
    ]
    return {
        "ok": not errors and not failed,
        "timestamp": _now_iso(),
        "mode": "stress_test",
        "scenario_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "blocked_new_trades_count": len(blocked),
        "risk_reduced_count": len(reduced),
        "critical_findings": critical_findings,
        "results": results,
        "warnings": warnings,
        "errors": errors,
    }


def run_default_stress_suite(
    trading_result: dict | None = None,
    config: dict | None = None,
) -> dict:
    return run_scenario_suite(trading_result=trading_result, scenarios=None, config=config)
