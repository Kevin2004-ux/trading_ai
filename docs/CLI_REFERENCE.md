# CLI Reference

All commands are run from the repository root:

```bash
.venv/bin/python cli.py <command> --pretty
```

The CLI does not expose buy, sell, order, or brokerage execution commands.

## Readiness And Database

- `config-check`: Validate startup configuration without live provider calls.
- `readiness-check`: Check runtime readiness. Add `--include-live-checks` only when you intentionally want provider checks.
- `db-migrate`: Apply pending SQLite migrations.
- `db-status`: Show schema, migration, audit, and pipeline status.
- `env-check`: Validate dependencies, environment variables, startup imports, and SQLite initialization.

## Provider Diagnostics

- `live-dry-run --ticker AAPL`: Safe provider availability dry run. May use live provider quotas if keys are configured.
- `ibkr-diagnose --ticker AAPL`: Read-only IBKR stock quote/historical/options-metadata diagnostic.
- `ibkr-options-diagnose --ticker AAPL`: Read-only small option quote diagnostic.
- `news-diagnostic`: Optional news provider diagnostic.

## Paper Trading

- `paper-cycle`: Run a simulated paper-trading cycle.
- `paper-review`: Review open simulated paper trades and optionally update outcomes.
- `paper-summary`: Show simulated paper-trading summary.
- `risk-diagnostics`: Show circuit breaker and setup decay diagnostics.

Safe stock-only example:

```bash
.venv/bin/python cli.py paper-cycle --universe mega_cap --max-tickers 25 --max-trades 2 --min-trades 0 --no-include-options --pretty
```

## Market And Technical Diagnostics

- `macro-calendar`: Show offline macro calendar.
- `macro-risk`: Evaluate macro risk controls.
- `correlation-refresh`: Refresh correlation matrix from historical bars.
- `correlation-status`: Show latest stored correlation snapshot.
- `concentration-check`: Evaluate one candidate against open paper trades.
- `volume-profile`: Build volume profile for one ticker.
- `timeframe-check`: Evaluate daily/weekly confirmation.

## Options Research

- `iv-rank`: Evaluate IV rank/percentile for first available option contract.
- `greeks-check`: Evaluate Greeks quality.
- `option-risk-check`: Evaluate option trade risk.
- `option-strategies`: Build research-only option strategy candidates.
- `option-strategy-check`: Inspect a requested strategy type.

Final option recommendations remain blocked unless quote, IV, Greeks, DTE, spread/fill, and strategy gates pass.

## Research

- `research-brief`: Build deterministic deep research brief.
- `sec-filings`: Fetch recent SEC filings when SEC research is configured.
- `filing-sentiment`: Analyze filing sentiment.
- `earnings-8k`: Analyze latest earnings-like 8-K.
- `short-interest`: Evaluate deterministic short-interest context.
- `news-sentiment`: Evaluate optional recent-news sentiment.

SEC/news commands may require configured provider keys or `SEC_USER_AGENT`.

## Memory And Journal

- `memory-status`: Show optional memory readiness.
- `memory-search`: Search optional semantic memory.
- `memory-store-note`: Store qualitative memory note.
- `annotate-trade`: Add human annotation.
- `annotations`: List and summarize annotations.
- `memory-events`: List memory retrieval events.
- `review-closed-trades`: Build deterministic post-trade reviews.
- `trade-reviews`: Fetch trade reviews.

Memory is qualitative only and cannot override deterministic gates.

## Reports, Jobs, Alerts, And Stress

- `report --type full_paper_trading --format markdown`: Generate full paper-trading report.
- `performance-report`: Generate performance diagnostics report.
- `jobs`: List registered jobs.
- `job-run --job stress_test`: Run one registered job explicitly.
- `jobs-due`: Run due jobs explicitly.
- `job-history`: List job history.
- `alerts`: List local alerts.
- `alert-test`: Create a local test alert.
- `stress-scenarios`: List stress scenarios.
- `stress-test --scenario market_gap_down`: Run one scenario against a sample paper candidate.
- `stress-suite`: Run the default deterministic stress suite.
- `portfolio-stress --scenario volatility_spike`: Stress open simulated paper trades.
- `data-failure-sim --scenario provider_outage`: Simulate data failure without provider calls.

## Gemini Validation

- `gemini-prompt-preview`: Preview structured Gemini prompts without calling Gemini.
- `validate-gemini-output --sample weekly-trade-hunt`: Validate mocked Gemini output.
- `format-trade-response`: Format deterministic fallback and validated sample output.

Gemini narration is optional and cannot override the deterministic trading engine.
