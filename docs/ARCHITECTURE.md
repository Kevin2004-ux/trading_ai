# Architecture

Trading AI is organized around deterministic paper-trading workflows. The LLM layer is an explanation layer; eligibility, logging, outcomes, and safety decisions are produced by structured code and SQLite records.

## High-Level Pipeline

```text
startup readiness
-> manual CLI / FastAPI / scheduled job runner
-> trading brain
-> universe builder and async scanner
-> provider routing and data-quality checks
-> technical, macro, research, options, memory, and risk gates
-> candidate ranking and weekly selection
-> simulated fills and slippage
-> paper logger
-> audit/checkpoints
-> outcome grading
-> reports, alerts, stress tests, and performance analytics
```

## Core Runtime

- `ui/app.py`: FastAPI app and dashboard/API routes.
- `cli.py`: Operational CLI for diagnostics, paper cycles, reports, jobs, readiness, and stress tests.
- `translator/main.py`: Optional Gemini integration and tool registration.
- `tools/agent_tools.py`: Safe tool wrappers that expose deterministic workflows to the LLM.

## Trading Brain And Selection

- `agent/trading_brain.py`: Coordinates weekly hunts, ticker reviews, final decision building, monitoring, and paper logging.
- `scanner/universe_builder.py`: Builds ticker universes.
- `scanner/swing_scanner.py`: Runs multi-profile swing scans.
- `scanner/scan_profiles.py`: Defines deterministic setup profiles.
- `selector/weekly_selector.py`: Selects 2-5 weekly paper candidates when constraints pass.

## Data And Provider Layer

- `realtime/market_data.py`: Canonical market snapshot, quote, bars, freshness, and technical snapshot interface.
- `providers/ibkr_provider.py`: Read-only IBKR/TWS market-data diagnostics and provider functions.
- `providers/market_data_provider.py`: Market data provider routing.
- `providers/options_data_provider.py`: Options provider routing.
- `providers/ticker_normalizer.py`: Provider-specific ticker normalization such as class-share symbols.
- `realtime/options_chain.py`: Options-chain normalization and provider access.

## Deterministic Gates

- `quality/data_quality.py`: Freshness, fallback, and data-quality gating.
- `macro/`: Offline macro calendar and macro-risk controls.
- `analytics/market_regime.py`: Granular market regime classification.
- `analytics/volume_profile.py`: Volume profile confirmation.
- `analytics/timeframe_confirmation.py`: Multi-timeframe confirmation.
- `risk/concentration_controls.py`: Position, sector, and correlation concentration gates.
- `risk/correlation_matrix.py`: Correlation snapshot refresh and lookup.
- `risk/position_sizing.py`: Simulated risk sizing.
- `options/`: IV rank, Greeks monitoring, option risk checks, and strategy comparison.
- `research/`: SEC EDGAR, filing analysis, filing sentiment, short interest, borrow pressure, news, and earnings context.
- `memory/`: Optional semantic memory, quality gates, human annotations, and feedback.

## Paper Trading And Persistence

- `tracking/trade_logger.py`: SQLite trade recommendations, candidate evaluations, scanner runs, outcomes, and trade-history queries.
- `tracking/outcome_grader.py`: Outcome grading for open paper recommendations.
- `paper/paper_trader.py`: Paper cycle, portfolio review, and paper-trading summary.
- `journal/trade_journal.py`: Deterministic post-trade review records.
- `db/schema_manager.py`: SQLite migration and schema validation.
- `db/audit_log.py`: Append-only audit chain.
- `db/checkpoints.py`: Pipeline checkpointing.

SQLite remains the source of truth for exact trade records, outcomes, job history, alerts, audit events, and deterministic performance.

## Reports, Alerts, Jobs, And Simulation

- `reports/report_generator.py`: Weekly plans, open-trade reviews, performance diagnostics, research memos, and post-trade reviews.
- `alerts/alert_rules.py`: Local structured alert rules.
- `alerts/alert_manager.py`: Alert persistence and optional delivery hooks.
- `jobs/job_registry.py`: Registered jobs. Stress jobs are disabled by default.
- `jobs/job_runner.py`: Explicit job execution and audit/alert integration.
- `simulation/`: Stress scenarios, stress engine, scenario runner, portfolio stress, and data-failure simulation.
- `analytics/performance_attribution.py`, `analytics/strategy_diagnostics.py`, `analytics/filter_attribution.py`, `analytics/trade_error_analysis.py`: Performance feedback loops.

## Safety Interaction Model

The engine should only recommend a paper trade when deterministic gates pass. A typical candidate can be downgraded or rejected by:

- Missing or stale data.
- Macro critical events.
- Weak technical confirmation.
- Concentration or correlation risk.
- Excessive slippage/fill risk.
- Options quote/IV/Greeks/fill failures.
- Research/news/filing risk.
- Circuit breaker or setup decay.
- Memory quality gates.
- Stress tests.

Gemini can explain why a candidate passed or failed, but it cannot make failed/watchlist/rejected candidates eligible. Alerts and reports summarize state; they do not execute trades.
