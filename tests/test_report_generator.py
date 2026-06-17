from reports.report_generator import (
    generate_full_paper_trading_report,
    generate_open_trade_review_report,
    generate_performance_diagnostics_report,
    generate_performance_report,
    generate_post_trade_review_report,
    generate_ticker_research_memo,
    generate_weekly_trade_plan_report,
)
from alerts.alert_manager import create_alert
from jobs.job_history import record_job_run
from tracking.trade_logger import init_trade_tracking_db, log_recommendation, log_trade_outcome


def test_weekly_trade_plan_report_returns_markdown_with_selected_trades():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"regime": "risk_on_uptrend", "summary": "Risk on."},
            "portfolio_risk": {"risk_summary": {"message": "Portfolio risk check completed."}},
            "selection_result": {
                "watchlist_alternatives": [{"ticker": "MSFT", "rejection_reason": "Watchlist only"}],
                "rejected_candidates": [{"ticker": "TSLA", "rejection_reason": "Weak setup"}],
            },
            "decision_result": {
                "final_recommendations": [
                    {
                        "ticker": "AAPL",
                        "asset_type": "stock",
                        "direction": "long",
                        "setup_type": "momentum_breakout",
                        "entry_price": 100.0,
                        "target_price": 110.0,
                        "stop_loss": 95.0,
                        "risk_reward": 2.0,
                        "position_sizing": {"shares": 20},
                        "thesis": "Breakout with confirmation.",
                        "invalidation": "Close below 95.",
                        "risks": ["Earnings next month"],
                        "paper_fill": {
                            "intended_entry_price": 100.0,
                            "estimated_fill_price": 100.08,
                            "fill_quality": "good",
                            "paper_fill_warning": "Paper stock fill includes deterministic slippage.",
                        },
                        "option_alternatives": [{"option_contract": "AAPL260703C00125000"}],
                    }
                ],
                "risk_rejected": [{"ticker": "NVDA", "rejection_reason": "Too much semiconductor concentration"}],
            },
        }
    )

    assert result["ok"] is True
    assert result["report_type"] == "weekly_trade_plan"
    assert "AAPL" in result["markdown"]
    assert "Option alternative" in result["markdown"]
    assert "Estimated paper fill" in result["markdown"]


def test_weekly_report_includes_data_quality_warnings():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {
                "message": "Weekly hunt complete.",
                "data_quality": {
                    "worst_quality_label": "usable_with_warnings",
                    "warnings": ["IBKR live quote unavailable; using latest historical close."],
                    "errors": [],
                },
            },
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "No trades approved."}},
            "scan_result": {
                "data_quality_summary": {
                    "worst_quality_label": "usable_with_warnings",
                    "warnings": ["Not suitable for intraday entry decisions."],
                    "errors": [],
                }
            },
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Data Quality" in result["markdown"]
    assert "latest historical close" in result["markdown"]


def test_weekly_report_includes_gemini_validation_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Portfolio risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
            "gemini_validation": {
                "validation_status": "pass",
                "safe_to_show_user": True,
                "safe_to_log": False,
                "deterministic_fallback_used": False,
                "issues": [],
            },
        }
    )

    assert result["ok"] is True
    assert "Gemini Validation" in result["markdown"]
    assert "Validation status: pass" in result["markdown"]
    assert "Safe to log: False" in result["markdown"]


def test_weekly_report_includes_memory_and_human_feedback_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {
                "message": "Weekly hunt complete.",
                "memory_summary": {
                    "enabled": True,
                    "evaluated_count": 1,
                    "decision_support_count": 0,
                    "explanation_only_count": 1,
                    "ignored_count": 0,
                    "warnings": ["Memory quality was explanation-only."],
                },
            },
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Portfolio risk check completed."}},
            "selection_result": {},
            "decision_result": {
                "final_recommendations": [
                    {
                        "ticker": "AAPL",
                        "entry_price": 100.0,
                        "target_price": 110.0,
                        "stop_loss": 95.0,
                        "risk_reward": 2.0,
                        "memory_context": {
                            "retrieval_quality": {
                                "quality_status": "warn",
                                "top_score": 0.78,
                                "usable_for_decision_support": False,
                                "usable_for_explanation": True,
                            },
                            "memory_impact": {
                                "trade_impact": "neutral",
                                "score_adjustment": 0.0,
                                "risk_multiplier": 1.0,
                            },
                            "human_feedback": {
                                "feedback_status": "caution",
                            },
                        },
                    }
                ]
            },
        }
    )

    assert result["ok"] is True
    assert "Memory And Human Feedback" in result["markdown"]
    assert "top_similarity=0.78" in result["markdown"]
    assert "Explanation-only: 1" in result["markdown"]


def test_weekly_report_includes_circuit_breaker_and_setup_decay_sections():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {
                "message": "Weekly hunt complete.",
                "circuit_breaker": {
                    "circuit_status": "reduced_risk",
                    "rolling_loss_streak": 5,
                    "recent_win_rate": 20.0,
                    "recent_expectancy_r": -0.4,
                    "max_allowed_risk_multiplier": 0.5,
                    "reasons": ["5 consecutive closed losses reached the reduced-risk threshold."],
                },
                "setup_decay": {
                    "setups": {
                        "momentum_breakout": {
                            "status": "decaying",
                            "sample_size": 12,
                            "recent_expectancy_r": -0.2,
                        }
                    }
                },
            },
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Circuit Breaker" in result["markdown"]
    assert "reduced_risk" in result["markdown"]
    assert "Setup Decay" in result["markdown"]
    assert "momentum_breakout" in result["markdown"]


def test_weekly_report_includes_scheduled_jobs_and_alerts_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
            "job_history": {
                "ok": True,
                "job_runs": [
                    {
                        "job_name": "weekly_paper_cycle",
                        "job_type": "paper_cycle",
                        "status": "success",
                        "started_at": "2026-06-15T13:00:00+00:00",
                    },
                    {
                        "job_name": "healthcheck",
                        "job_type": "healthcheck",
                        "status": "failed",
                        "started_at": "2026-06-15T12:00:00+00:00",
                    },
                ],
            },
            "alert_summary": {
                "ok": True,
                "count": 2,
                "severity_counts": {"warning": 1, "critical": 1},
                "alerts": [],
            },
        }
    )

    assert result["ok"] is True
    assert "Scheduled Jobs And Alerts" in result["markdown"]
    assert "weekly_paper_cycle" in result["markdown"]
    assert "Severity counts" in result["markdown"]


def test_weekly_report_includes_stress_test_summary_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {
                "message": "Weekly hunt complete.",
                "stress_test_summary": {
                    "mode": "stress_test",
                    "scenario_count": 2,
                    "passed_count": 2,
                    "failed_count": 0,
                    "blocked_new_trades_count": 1,
                    "risk_reduced_count": 2,
                    "results": [
                        {"scenario_name": "market_gap_down", "severity": "high", "passed_expected_behavior": True},
                        {"scenario_name": "provider_outage", "severity": "extreme", "passed_expected_behavior": True},
                    ],
                    "critical_findings": [{"scenario_name": "provider_outage", "message": "Blocked new simulated trades."}],
                },
            },
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Stress Test Summary" in result["markdown"]
    assert "Scenarios run: 2" in result["markdown"]
    assert "provider_outage" in result["markdown"]


def test_weekly_report_includes_performance_diagnostics_sections():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
            "performance_attribution": {
                "closed_trade_count": 12,
                "open_trade_count": 2,
                "win_rate": 50.0,
                "expectancy_r": -0.1,
                "profit_factor": 0.8,
                "max_drawdown_r": -2.0,
                "warnings": ["Sample is paper-only."],
            },
            "setup_diagnostics": {
                "overall_status": "degrading",
                "setups": [{"setup_type": "breakout", "status": "decaying", "expectancy_r": -0.2, "win_rate": 35.0}],
                "recommendations": ["Review breakout."],
            },
            "filter_attribution": {
                "filters": [{"filter_name": "data_quality", "diagnostic_status": "neutral", "applied_count": 5, "blocked_count": 1, "downgraded_count": 2}],
                "warnings": [],
            },
            "trade_error_analysis": {
                "top_failure_modes": [{"category": "stop_too_tight", "count": 3}],
                "recommendations": ["Review stops."],
            },
        }
    )

    assert result["ok"] is True
    assert "Performance Attribution" in result["markdown"]
    assert "Setup Diagnostics" in result["markdown"]
    assert "Filter Attribution" in result["markdown"]
    assert "Trade Error Analysis" in result["markdown"]


def test_weekly_report_includes_macro_risk_and_granular_regime_sections():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "macro_risk": {
                "macro_risk_level": "high",
                "risk_multiplier": 0.5,
                "new_trades_allowed": True,
                "active_events": [{"event_type": "JOBS"}],
                "upcoming_events": [],
                "warnings": ["Macro risk reduced position sizing multiplier to 0.5."],
                "reasons": ["1 macro risk window(s) active."],
            },
            "market_regime": {
                "regime": "weak_bull_chop",
                "risk_level": "medium",
                "confidence": 0.65,
                "stock_risk_multiplier": 0.75,
                "option_risk_multiplier": 0.5,
                "allowed_setups": ["trend_pullback"],
                "blocked_setups": ["low_quality_breakout"],
                "warnings": ["Market breadth is mixed."],
            },
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Macro Risk" in result["markdown"]
    assert "Risk level: high" in result["markdown"]
    assert "weak_bull_chop" in result["markdown"]
    assert "Stock risk multiplier: 0.75" in result["markdown"]


def test_weekly_report_includes_correlation_and_concentration_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "concentration_summary": {
                "ok": True,
                "snapshot": {
                    "source": "latest_snapshot",
                    "latest_snapshot": {
                        "snapshot": {
                            "age_hours": 4.2,
                            "snapshot_id": "snap-1",
                        }
                    },
                    "warnings": ["AAPL/MSFT highly correlated."],
                },
                "evaluated_count": 2,
                "blocked_count": 1,
                "reduced_count": 1,
                "evaluations": [
                    {
                        "ticker": "AAPL",
                        "concentration_risk": {
                            "risk_level": "high",
                            "risk_multiplier": 0.5,
                        },
                    }
                ],
            },
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Correlation And Concentration" in result["markdown"]
    assert "Latest snapshot age hours: 4.20" in result["markdown"]
    assert "Blocked candidates: 1" in result["markdown"]
    assert "multiplier=0.50" in result["markdown"]


def test_weekly_report_includes_technical_confirmation_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
            "technical_confirmation_summary": {
                "ok": True,
                "evaluated_count": 1,
                "rejected_count": 0,
                "warning_count": 1,
                "evaluations": [
                    {
                        "ticker": "AAPL",
                        "technical_confirmation_summary": {
                            "status": "warning",
                            "score_adjustment": -5.0,
                            "risk_multiplier": 0.75,
                        },
                        "volume_profile_confirmation": {
                            "point_of_control": 100.0,
                            "value_area_low": 95.0,
                            "value_area_high": 110.0,
                        },
                        "timeframe_confirmation": {
                            "daily_trend": "uptrend",
                            "weekly_trend": "unknown",
                        },
                    }
                ],
            },
        }
    )

    assert result["ok"] is True
    assert "Technical Confirmation" in result["markdown"]
    assert "POC=$100.00" in result["markdown"]
    assert "daily=uptrend" in result["markdown"]


def test_weekly_report_includes_sec_filing_sentiment_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {
                "filing_sentiment_summary": {
                    "ok": True,
                    "evaluated_count": 1,
                    "blocking_count": 1,
                    "high_risk_count": 0,
                    "evaluations": [
                        {
                            "ticker": "AAPL",
                            "bucket": "rejected_candidates",
                            "filing_analysis": {
                                "filing_risk_level": "critical",
                                "material_events": ["restatement/amendment"],
                            },
                            "earnings_8k_analysis": {"sentiment_label": "unknown"},
                            "filing_sentiment": {
                                "sentiment_label": "negative",
                                "filing_risk_level": "critical",
                                "trade_impact": "blocking",
                                "risk_multiplier": 0.0,
                            },
                        }
                    ],
                }
            },
            "decision_result": {
                "final_recommendations": [
                    {
                        "ticker": "MSFT",
                        "asset_type": "stock",
                        "direction": "long",
                        "setup_type": "momentum_breakout",
                        "entry_price": 100.0,
                        "target_price": 110.0,
                        "stop_loss": 95.0,
                        "risk_reward": 2.0,
                        "filing_sentiment": {
                            "sentiment_label": "neutral",
                            "filing_risk_level": "low",
                            "trade_impact": "neutral",
                            "risk_multiplier": 1.0,
                        },
                    }
                ]
            },
        }
    )

    assert result["ok"] is True
    assert "SEC Filing Sentiment" in result["markdown"]
    assert "Critical/blocking candidates: 1" in result["markdown"]
    assert "restatement/amendment" in result["markdown"]
    assert "Filing sentiment: neutral" in result["markdown"]


def test_weekly_report_includes_short_interest_and_news_risk_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "research_risk_summary": {
                "ok": True,
                "evaluated_count": 1,
                "blocking_count": 0,
                "reduced_count": 1,
                "evaluations": [
                    {
                        "ticker": "AAPL",
                        "bucket": "selected_trades",
                        "short_interest": {
                            "short_interest_level": "extreme",
                            "days_to_cover": 8.0,
                            "squeeze_risk": "high",
                        },
                        "borrow_pressure": {"borrow_pressure": "medium"},
                        "news_sentiment": {
                            "sentiment_label": "negative",
                            "headline_risk_level": "high",
                            "risk_flags": ["investigation"],
                        },
                    }
                ],
            },
            "selection_result": {},
            "decision_result": {
                "final_recommendations": [
                    {
                        "ticker": "AAPL",
                        "asset_type": "stock",
                        "direction": "long",
                        "setup_type": "momentum_breakout",
                        "entry_price": 100.0,
                        "target_price": 110.0,
                        "stop_loss": 95.0,
                        "risk_reward": 2.0,
                        "short_interest": {"short_interest_level": "extreme", "days_to_cover": 8.0, "squeeze_risk": "high"},
                        "borrow_pressure": {"borrow_pressure": "medium"},
                        "news_sentiment": {"sentiment_label": "negative", "headline_risk_level": "high", "risk_flags": ["investigation"]},
                    }
                ]
            },
        }
    )

    assert result["ok"] is True
    assert "Short Interest And News Risk" in result["markdown"]
    assert "short=extreme" in result["markdown"]
    assert "Borrow pressure: medium" in result["markdown"]
    assert "Headline risk flags: investigation" in result["markdown"]


def test_weekly_report_includes_options_iv_and_greeks_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
            "option_risk_summary": {
                "ok": True,
                "evaluated_count": 1,
                "approved_count": 0,
                "research_only_count": 0,
                "blocked_count": 1,
                "evaluations": [
                    {
                        "option_contract": "AAPL260717C00125000",
                        "iv_context": {"iv_context": "unknown", "iv_rank": None, "iv_percentile": None},
                        "greeks_monitoring": {"greeks_quality": "unavailable"},
                        "option_trade_risk": {
                            "status": "blocked",
                            "days_to_expiration": 32,
                            "spread_quality": "unavailable",
                            "fill_quality": "unavailable",
                        },
                    }
                ],
            },
        }
    )

    assert result["ok"] is True
    assert "Options IV And Greeks Risk" in result["markdown"]
    assert "Blocked contracts: 1" in result["markdown"]
    assert "greeks=unavailable" in result["markdown"]


def test_weekly_report_includes_option_strategy_section():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
            "option_research": {
                "option_strategy_candidates": [
                    {
                        "strategy_type": "bull_call_debit_spread",
                        "status": "paper_eligible",
                        "net_debit": 2.0,
                        "net_credit": None,
                        "max_loss": 2.0,
                        "max_profit": 3.0,
                        "breakeven": 127.0,
                    }
                ],
                "summary": {
                    "option_strategy_summary": {
                        "strategy_count": 1,
                        "paper_eligible_count": 1,
                        "research_only_count": 0,
                        "blocked_count": 0,
                    }
                },
            },
        }
    )

    assert result["ok"] is True
    assert "Option Strategy Comparison" in result["markdown"]
    assert "bull_call_debit_spread" in result["markdown"]
    assert "Paper-eligible strategies: 1" in result["markdown"]


def test_weekly_report_includes_scan_execution_summary():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {
                "message": "Weekly hunt complete.",
                "scan_execution_summary": {
                    "total_tickers": 10,
                    "completed_tickers": 8,
                    "failed_tickers": ["BAD"],
                    "timed_out_tickers": ["SLOW"],
                    "partial_results_used": True,
                    "duration_seconds": 12.5,
                    "warnings": ["Scan completed with partial results due to timeout or provider failures."],
                },
            },
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Scan Execution" in result["markdown"]
    assert "Completed tickers: 8" in result["markdown"]
    assert "Timed-out tickers: 1" in result["markdown"]
    assert "partial results" in result["markdown"].lower()


def test_weekly_report_includes_pipeline_and_audit_summary():
    result = generate_weekly_trade_plan_report(
        {
            "run_id": "paper_cycle_abc",
            "pipeline_run": {"run_id": "paper_cycle_abc", "status": "completed"},
            "checkpoint_summary": {"count": 7},
            "audit_status": {"ok": True, "event_count": 12},
            "schema_version": {"current_version": "005_trade_tracking_tables"},
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"summary": "Risk neutral."},
            "portfolio_risk": {"risk_summary": {"message": "Risk check completed."}},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Pipeline And Audit" in result["markdown"]
    assert "paper_cycle_abc" in result["markdown"]
    assert "Audit chain ok: True" in result["markdown"]
    assert "005_trade_tracking_tables" in result["markdown"]


def test_weekly_report_includes_startup_readiness_summary():
    result = generate_weekly_trade_plan_report(
        {
            "startup_readiness": {
                "readiness": "not_ready",
                "safe_to_run_paper_cycle": False,
                "safe_to_run_options": False,
                "warnings": ["Historical fallback enabled."],
                "errors": ["IBKR_READ_ONLY must be true when IBKR is configured."],
            },
            "summary": {"message": "Paper trading cycle blocked by startup validation."},
            "market_regime": {},
            "portfolio_risk": {},
            "selection_result": {},
            "decision_result": {"final_recommendations": []},
        }
    )

    assert result["ok"] is True
    assert "Startup Readiness" in result["markdown"]
    assert "not_ready" in result["markdown"]
    assert "IBKR_READ_ONLY" in result["markdown"]


def test_open_trade_review_report_includes_open_closed_and_manual_review_sections():
    result = generate_open_trade_review_report(
        {
            "open_paper_trades": [{"ticker": "AAPL", "status": "open", "entry_price": 100.0, "target_price": 110.0, "stop_loss": 95.0}],
            "recently_closed_paper_trades": [{"ticker": "MSFT", "outcome": "win", "exit_price": 108.0}],
            "win_loss_record": {"wins": 1, "losses": 0, "expired": 0, "open": 1, "win_rate": 100.0},
            "trade_review_summary": {"reviewed_count": 1, "skipped_count": 0},
            "monitoring_result": {"update_result": {"results": [{"ticker": "TSLA", "outcome": "manual_review", "exit_reason": "same_bar_ambiguity"}]}},
        }
    )

    assert result["ok"] is True
    assert "Open Trades" in result["markdown"]
    assert "Newly Closed Trades" in result["markdown"]
    assert "Manual Review Needed" in result["markdown"]


def test_performance_report_includes_win_rate_and_simulation_warning():
    result = generate_performance_report(
        {
            "win_loss_record": {"total_recommendations": 4, "closed_trades": 3, "open": 1, "wins": 2, "losses": 1, "win_rate": 66.67},
            "strategy_performance": {
                "by_strategy": [{"strategy": "breakout", "average_realized_return": 4.2}],
                "by_setup_type": [
                    {"setup_type": "momentum_breakout", "average_realized_return": 5.0},
                    {"setup_type": "pullback", "average_realized_return": -1.0},
                ],
            },
            "setup_performance": [{"setup_type": "momentum_breakout", "expectancy": 0.4}],
        }
    )

    assert result["ok"] is True
    assert "66.67" in result["markdown"]
    assert "simulated only" in result["markdown"].lower()


def test_ticker_research_memo_includes_bull_bear_and_evidence_table():
    result = generate_ticker_research_memo(
        {
            "ticker": "AAPL",
            "research_summary": "AAPL research summary.",
            "trade_thesis": {"thesis": "Constructive trend continuation."},
            "bull_case": {"points": ["Above 50-day moving average."]},
            "bear_case": {"points": ["Macro slowdown risk."]},
            "key_risks": ["Valuation risk"],
            "evidence_table": [{"category": "technical", "claim": "Trend intact", "source": "system"}],
            "research_conviction": {"label": "medium", "score": 68},
            "data_quality": {"missing_sections": [], "stale_data_flags": []},
        }
    )

    assert result["ok"] is True
    assert "Bull Case" in result["markdown"]
    assert "Bear Case" in result["markdown"]
    assert "Trend intact" in result["markdown"]


def test_post_trade_review_report_includes_lessons_and_trade_quality():
    result = generate_post_trade_review_report(
        [
            {
                "ticker": "AAPL",
                "outcome": "win",
                "trade_quality_label": "good_process",
                "thesis_validity": "valid",
                "review_summary": "Clean process win.",
                "lessons_json": [{"tag": "winner_followed_thesis"}],
                "mistakes_json": [],
                "strengths_json": ["Respected the plan."],
                "rule_adjustments_json": ["Keep current breakout filters."],
                "memory_status_json": {"ok": False, "source": "disabled"},
            }
        ]
    )

    assert result["ok"] is True
    assert "good_process" in result["markdown"]
    assert "winner_followed_thesis" in result["markdown"]


def test_full_paper_trading_report_returns_partial_report_cleanly_on_empty_db(tmp_path):
    db_path = str(tmp_path / "empty_reports.db")
    init_trade_tracking_db(db_path)

    result = generate_full_paper_trading_report(db_path=db_path)

    assert result["ok"] is True
    assert result["report_type"] == "full_paper_trading"
    assert "Open Recommendations" in result["markdown"]


def test_unsupported_format_returns_clean_error():
    result = generate_weekly_trade_plan_report({"decision_result": {}}, format="html")

    assert result["ok"] is False
    assert "Unsupported report format" in result["error"]


def test_full_paper_trading_report_can_include_real_rows(tmp_path):
    db_path = str(tmp_path / "full_report.db")
    init_trade_tracking_db(db_path)
    recommendation = log_recommendation(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="report_strategy",
        setup_type="momentum_breakout",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.0,
        db_path=db_path,
        data_snapshot_json={"paper_trading": True, "execution_mode": "paper_trading"},
        model_outputs_json={"paper_trading": True, "execution_mode": "paper_trading"},
    )
    log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=108.0,
        db_path=db_path,
    )

    result = generate_full_paper_trading_report(db_path=db_path, format="dict")

    assert result["ok"] is True
    assert result["format"] == "dict"
    assert result["sections"]


def test_full_paper_trading_report_includes_job_history_and_alerts(tmp_path):
    db_path = str(tmp_path / "full_report_ops.db")
    init_trade_tracking_db(db_path)
    record_job_run(
        db_path=db_path,
        job_run_id="job-run-ops",
        job_name="weekly_paper_cycle",
        job_type="paper_cycle",
        status="success",
        started_at="2026-06-15T13:00:00+00:00",
        completed_at="2026-06-15T13:00:01+00:00",
        duration_seconds=1.0,
        result={"ok": True},
    )
    create_alert(
        db_path=db_path,
        severity="warning",
        alert_type="data_quality_degraded",
        title="Data warning",
        message="Historical fallback used.",
    )

    result = generate_full_paper_trading_report(db_path=db_path, format="dict")

    assert result["ok"] is True
    assert any(section["title"] == "Scheduled Jobs And Alerts" for section in result["sections"])
    assert "weekly_paper_cycle" in result["markdown"]
    assert "warning" in result["markdown"]


def test_performance_diagnostics_report_reads_sqlite_history(tmp_path):
    db_path = str(tmp_path / "performance_diagnostics.db")
    init_trade_tracking_db(db_path)
    recommendation = log_recommendation(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="report_strategy",
        setup_type="momentum_breakout",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.0,
        db_path=db_path,
        data_snapshot_json={"data_quality": "pass"},
    )
    log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=110.0,
        db_path=db_path,
    )

    result = generate_performance_diagnostics_report(db_path=db_path, format="dict")

    assert result["ok"] is True
    assert result["report_type"] == "performance_diagnostics"
    assert any(section["title"] == "Performance Attribution" for section in result["sections"])
    assert "simulated paper trades only" in result["summary"]
