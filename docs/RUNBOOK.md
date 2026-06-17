# Trading AI Runbook

## 1. Create a Virtual Environment

Use Python 3.11 or 3.12 for the local runtime. Python 3.13 may fail to install the current
PyTorch dependency because compatible wheels may not be available yet.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

On this machine, Python 3.12 is available at:

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv .venv
```

## 2. Install Dependencies

Install the runtime and test dependencies from the repo root:

```bash
python -m pip install -r requirements.txt
```

This install step is required before the FastAPI dashboard and UI route tests can run. If
`fastapi`, `httpx`, or related runtime packages are missing locally, `tests/test_ui_routes.py`
will skip cleanly instead of hiding the missing dependency.

If you are installing from the package metadata instead:

```bash
python -m pip install -e .[test]
```

## 3. Environment Variables

These keys are optional for startup, but some routes and tools use them when available:

- `GEMINI_API_KEY`
  - Optional for `/ask` chat behavior and Gemini-backed translator features.
- `POLYGON_API_KEY`
  - Optional for live/recent market data.
- `FMP_API_KEY`
  - Optional for news, earnings, and catalyst enrichment.
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
  - Optional for semantic memory. Defaults to `trading-ai-memory`.
- `PINECONE_NAMESPACE`
  - Optional namespace for semantic memory. Defaults to `trading_ai`.
- `MEMORY_EMBEDDING_PROVIDER`
  - Optional embedding provider setting for semantic memory.
- `PINECONE_ENVIRONMENT`
  - Optional companion setting for Pinecone.

Start from the safe template:

```bash
cp .env.example .env
```

Safe local `.env` shape:

```env
MARKET_DATA_PROVIDER=ibkr
OPTIONS_DATA_PROVIDER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=123
IBKR_READ_ONLY=true
MARKET_DATA_MODE=auto
ALLOW_HISTORICAL_BAR_FALLBACK=true
ALLOW_LIVE_QUOTE_REQUIRED=false
ALLOW_OPTIONS_WITHOUT_QUOTES=false
GEMINI_API_KEY=
POLYGON_API_KEY=
FMP_API_KEY=
PINECONE_API_KEY=
PINECONE_INDEX_NAME=
SEC_USER_AGENT="TradingAI Your Name email@example.com"
```

Optional scheduler and local alert settings:

```env
SCHEDULER_ENABLED=false
SCHEDULER_TIMEZONE=America/New_York
SCHEDULER_MARKET_DAYS_ONLY=true
DEFAULT_PAPER_SCAN_DAY=MON
DEFAULT_PAPER_SCAN_TIME=09:00
DEFAULT_HEALTHCHECK_TIME=08:30
ALERTS_ENABLED=true
ALERT_CHANNELS=local
ALERT_MIN_SEVERITY=warning
ALERT_WEBHOOK_URL=
ALERT_EMAIL_ENABLED=false
```

Alerts are structured SQLite events by default. Webhook and email channels are intentionally
configured-not-sent unless a future project-specific sender is explicitly added and tested.

Missing keys should not crash startup:

- chat stays unavailable without `GEMINI_API_KEY`
- market/news/catalyst routes return clean unavailable responses without `POLYGON_API_KEY` or `FMP_API_KEY`
- semantic memory remains optional without `PINECONE_API_KEY`

## 4. Environment Checklist

From a fresh shell, verify the local runtime before running live paper-trading dry runs:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python cli.py env-check --pretty
```

The environment check reports:

- Python version
- required and optional package availability
- optional API key presence
- SQLite initialization status
- FastAPI app import status
- CLI import status

Missing optional API keys are warnings, not startup failures. Missing required Python packages
are errors and should be fixed with `python -m pip install -r requirements.txt`.

## 5. Run Tests

Run the focused UI route suite:

```bash
python -m pytest tests/test_ui_routes.py -q
```

Run the focused trade-journal suite:

```bash
python -m pytest tests/test_trade_journal.py -q
```

Run the focused report suite:

```bash
python -m pytest tests/test_report_generator.py -q
```

Run the focused scheduled-jobs and alerts suites:

```bash
python -m pytest tests/test_job_registry.py tests/test_scheduler.py tests/test_job_history.py tests/test_job_runner.py tests/test_alert_channels.py tests/test_alert_manager.py tests/test_alert_rules.py -q
```

Run the focused macro/regime risk suites:

```bash
python -m pytest tests/test_macro_calendar.py tests/test_macro_risk.py tests/test_market_regime_granularity.py -q
```

Run the full offline suite:

```bash
python -m pytest tests/test_trade_logger.py tests/test_market_data.py tests/test_constraint_engine.py tests/test_swing_scanner.py tests/test_outcome_grader.py tests/test_agent_tools.py tests/test_scan_profiles.py tests/test_statistical_brain.py tests/test_universe_builder.py tests/test_weekly_selector.py tests/test_catalyst_enrichment.py tests/test_translator.py tests/test_agent_workflow.py tests/test_trading_brain.py tests/test_paper_trader.py tests/test_paper_jobs.py tests/test_cli.py tests/test_ui_routes.py tests/test_options_chain.py tests/test_options_scanner.py tests/test_options_mispricing.py tests/test_market_regime.py tests/test_relative_strength.py tests/test_deep_research.py tests/test_sec_filings.py tests/test_earnings_transcripts.py tests/test_portfolio_manager.py tests/test_position_sizing.py tests/test_vector_memory.py tests/test_trade_journal.py tests/test_report_generator.py tests/test_healthcheck.py tests/test_live_dry_run.py tests/test_job_registry.py tests/test_scheduler.py tests/test_job_history.py tests/test_job_runner.py tests/test_alert_channels.py tests/test_alert_manager.py tests/test_alert_rules.py -q
```

## 6. Start the FastAPI App

From the repo root:

```bash
python -m uvicorn ui.app:app --reload
```

Default local URL:

```text
http://127.0.0.1:8000
```

Dashboard:

```text
http://127.0.0.1:8000/
```

## 7. Live-Readiness Dry Runs

Run a provider availability dry run:

```bash
python cli.py live-dry-run --ticker AAPL --pretty
```

Include optional semantic memory diagnostics:

```bash
python cli.py live-dry-run --ticker AAPL --include-memory --pretty
```

This command may call configured live providers and use API quota, but it does not place trades
and does not log final recommendations. Missing provider keys return clean unavailable statuses.

### IBKR Read-Only Market Data

To use TWS as the read-only market/options data provider, configure TWS:

- Enable ActiveX and Socket Clients.
- Enable Read-Only API.
- Keep localhost-only connections enabled.
- Use socket port `7496` for live TWS, or your configured paper/live TWS port.
- Keep this app free of brokerage execution routes. It does not place orders.

Set the local `.env` values:

```env
MARKET_DATA_PROVIDER=ibkr
OPTIONS_DATA_PROVIDER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=123
IBKR_READ_ONLY=true
IBKR_USE_DELAYED_DATA=true
```

`IBKR_USE_DELAYED_DATA=true` requests delayed data mode. Live market data still requires the
appropriate IBKR subscriptions. IBKR options support currently checks option-chain metadata and
returns clean unavailable/partial status for full quote chains until quote-chain support is
explicitly completed.

IBKR historical daily bars may be available even when live or delayed quote snapshots are not.
Error `10089` usually indicates a market data subscription or permission issue. For after-close
swing-trading scans, the system may use the latest historical daily close as a clearly labeled
`historical_bar_fallback` when quote snapshots are unavailable. For intraday entry timing, live
quote checks, option spread checks, or same-day option quote work, enable the required IBKR market
data subscriptions or use another configured provider.

Verify read-only provider availability:

```bash
python cli.py env-check --pretty
python cli.py live-dry-run --ticker AAPL --pretty
python cli.py ibkr-diagnose --ticker AAPL --pretty
```

Manual live-readiness checklist when TWS is open:

```bash
.venv/bin/python cli.py ibkr-diagnose --ticker AAPL --pretty
.venv/bin/python cli.py ibkr-diagnose --ticker SPY --pretty
.venv/bin/python cli.py ibkr-options-diagnose --ticker AAPL --pretty
```

Expected current behavior:

- Stock quotes and historical bars should work when TWS is open and permissions are available.
- Options metadata may work.
- Options quotes may remain unavailable without OPRA/options quote permissions.
- Final option recommendations stay blocked unless every option quote, IV, Greeks, risk, and fill gate passes.

Run a stock-only simulated paper cycle:

```bash
python cli.py paper-cycle \
  --universe mega_cap \
  --max-tickers 25 \
  --max-trades 2 \
  --min-trades 0 \
  --no-include-options \
  --include-market-regime \
  --include-relative-strength \
  --include-portfolio-risk \
  --include-position-sizing \
  --pretty
```

Paper trades are simulated records only. The app has no brokerage execution route and no CLI
command that places buy, sell, or order instructions.

### Macro Calendar And Risk Controls

The macro calendar is currently an offline/static risk-control feed. It is used to block or
reduce new simulated recommendations around major events such as CPI, FOMC, jobs reports, OPEX,
and earnings clusters. It does not call a live calendar API.

Inspect upcoming events:

```bash
python cli.py macro-calendar --days 14 --pretty
```

Evaluate current macro-event risk:

```bash
python cli.py macro-risk --pretty
```

Critical active macro windows can block new final recommendations. High/medium windows can reduce
position sizing through the same deterministic risk multiplier path used by circuit breakers and
market-regime controls.

## 8. Example API Calls

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Environment diagnostics:

```bash
curl "http://127.0.0.1:8000/diagnostics/environment"
```

Live provider dry run:

```bash
curl -X POST http://127.0.0.1:8000/diagnostics/live-dry-run \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "AAPL",
    "include_market_data": true,
    "include_news": true,
    "include_sec_filings": true,
    "include_earnings_transcripts": true,
    "include_options": true,
    "include_memory": false,
    "db_path": "strategy_library.db"
  }'
```

Run the weekly trade hunt:

```bash
curl -X POST http://127.0.0.1:8000/brain/weekly-trade-hunt \
  -H "Content-Type: application/json" \
  -d '{
    "universe": "large_cap",
    "max_tickers": 100,
    "max_trades": 5,
    "min_trades": 2,
    "include_catalysts": true,
    "auto_log": false,
    "db_path": "strategy_library.db"
  }'
```

Review one ticker:

```bash
curl "http://127.0.0.1:8000/brain/review-ticker/AAPL?include_catalysts=true&include_research_brief=true"
```

Check performance:

```bash
curl "http://127.0.0.1:8000/trades/performance"
```

Review closed trades into the deterministic journal:

```bash
curl -X POST http://127.0.0.1:8000/journal/review-closed-trades \
  -H "Content-Type: application/json" \
  -d '{
    "db_path": "strategy_library.db",
    "store_memory": false
  }'
```

Fetch trade reviews:

```bash
curl "http://127.0.0.1:8000/journal/reviews?ticker=AAPL&db_path=strategy_library.db"
```

Generate a consolidated paper-trading report:

```bash
curl -X POST http://127.0.0.1:8000/reports/generate \
  -H "Content-Type: application/json" \
  -d '{
    "report_type": "full_paper_trading",
    "payload": {},
    "format": "markdown",
    "db_path": "strategy_library.db"
  }'
```

Get the paper-summary report directly:

```bash
curl "http://127.0.0.1:8000/reports/paper-summary?format=markdown&db_path=strategy_library.db"
```

## 9. Dashboard

After starting FastAPI with:

```bash
python -m uvicorn ui.app:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

The dashboard can be used to:

- run a paper cycle
- review the paper portfolio
- generate a full paper-trading report
- generate a performance report
- review post-trade report output
- research a ticker through the current deterministic review path
- run environment diagnostics
- run a live-provider dry run for a ticker

The diagnostics panel is marked as dry-run only. Provider checks may use live API quotas, but no
trades are placed. The output panel shows raw JSON and, when available, markdown report output as
plain text. The page is paper-trading only, does not place brokerage orders, and should not be
treated as financial advice.

## 10. Paper-Trading CLI

Run the weekly simulated paper-trading cycle:

```bash
python cli.py paper-cycle --pretty
```

Run the weekly cycle with option alternatives included:

```bash
python cli.py paper-cycle --include-options --pretty
```

Allow the brain to prefer options only when strict option constraints pass:

```bash
python cli.py paper-cycle --include-options --prefer-options --pretty
```

Run the daily simulated paper portfolio review:

```bash
python cli.py paper-review --pretty
```

Run the daily review without journal reviews:

```bash
python cli.py paper-review --no-include-trade-reviews --pretty
```

Get the simulated paper-trading summary:

```bash
python cli.py paper-summary --pretty
```

Build a deterministic deep research brief for one ticker:

```bash
python cli.py research-brief --ticker AAPL --pretty
```

Search optional semantic memory:

```bash
python cli.py memory-search --query "AAPL breakout with high IV" --pretty
```

Store a qualitative memory note:

```bash
python cli.py memory-store-note --ticker AAPL --note "Breakout thesis weakened after failed follow-through." --pretty
```

Build deterministic reviews for closed trades that do not already have journal reviews:

```bash
python cli.py review-closed-trades --pretty
```

Fetch journal reviews by ticker:

```bash
python cli.py trade-reviews --ticker AAPL --pretty
```

Generate a report as JSON:

```bash
python cli.py report --type performance --format dict --pretty
```

Generate a readable markdown report:

```bash
python cli.py report --type full_paper_trading --format markdown --pretty
```

Include SEC filing and earnings transcript context explicitly:

```bash
python cli.py research-brief --ticker AAPL --include-sec-filings --include-earnings-transcripts --pretty
```

Useful flags:

- `--universe large_cap`
- `--max-tickers 500`
- `--max-trades 5`
- `--min-trades 2`
- `--include-catalysts` or `--no-include-catalysts`
- `--include-options` or `--no-include-options`
- `--prefer-options` or `--no-prefer-options`
- `--max-option-contracts-per-trade 3`
- `--include-portfolio-risk` or `--no-include-portfolio-risk`
- `--include-position-sizing` or `--no-include-position-sizing`
- `--include-memory-context` or `--no-include-memory-context`
- `--store-memory` or `--no-store-memory`
- `--include-trade-reviews` or `--no-include-trade-reviews`
- `--store-review-memory` or `--no-store-review-memory`
- `--account-size 10000`
- `--risk-mode normal`
- `--update-outcomes` or `--no-update-outcomes`
- `--ticker AAPL`
- `--type full_paper_trading`
- `--format markdown` or `--format dict`
- `--include-sec-filings` or `--no-include-sec-filings`
- `--include-earnings-transcripts` or `--no-include-earnings-transcripts`
- `--db-path strategy_library.db`

These commands are simulation-only. They log paper trades into SQLite and do not place live brokerage orders.
`--include-options` adds option alternatives for research. `--prefer-options` only lets the brain choose an option when strict deterministic option constraints pass. Neither mode places real trades.
`--include-position-sizing` attaches suggested share size or contract count for paper/research use only. It does not place orders and should not be treated as financial advice.
Semantic memory is optional and qualitative. It can store trade theses, research summaries, and notes for later similarity lookup, but SQLite remains authoritative for exact entries, exits, outcomes, and performance.

Trade journal reviews are deterministic post-trade process reviews stored in SQLite. A winning trade is not automatically good process, and a losing trade is not automatically bad process. If `--store-review-memory` or `store_memory=true` is used, journal summaries may also be sent to optional semantic memory as qualitative context only; SQLite remains the source of truth.

Reports are deterministic summaries of structured system outputs. They can summarize weekly plans, open-trade reviews, performance, ticker research, and post-trade reviews, but they do not create trades by themselves. Reports preserve warnings, missing data, and simulation caveats instead of smoothing them away.

The research brief is an evidence summary, not a guaranteed prediction. It can show a strong thesis and still conclude that no final trade qualifies under the hard constraints.

## 11. Scheduled Jobs And Alerts

This repo does not auto-start a scheduler on import. Scheduled jobs are simulated/paper-only and
must be triggered explicitly through the CLI, `cron`, GitHub Actions, or another external job
runner. No job places real brokerage orders.

List registered jobs:

```bash
python cli.py jobs --pretty
```

Run one registered job in safe dry-run mode:

```bash
python cli.py job-run --job weekly_paper_cycle --pretty
```

Run due jobs in safe dry-run mode:

```bash
python cli.py jobs-due --pretty
```

View job history:

```bash
python cli.py job-history --pretty
```

View local structured alerts:

```bash
python cli.py alerts --pretty
```

Create a local test alert without external sends:

```bash
python cli.py alert-test --severity warning --pretty
```

The local scheduler helper understands interval, daily, and weekly schedules, but it is not started
automatically by importing the app. Keep `SCHEDULER_ENABLED=false` unless you have an explicit
runner process supervising job execution.

Example `cron` entries:

Weekly paper cycle every Monday at 8:30 AM local time:

```cron
30 8 * * 1 cd /Users/kevinfrederick/trading_ai && /Users/kevinfrederick/trading_ai/.venv/bin/python cli.py paper-cycle --pretty >> /tmp/trading_ai_paper_cycle.log 2>&1
```

Daily paper review after market close at 6:15 PM local time:

```cron
15 18 * * 1-5 cd /Users/kevinfrederick/trading_ai && /Users/kevinfrederick/trading_ai/.venv/bin/python cli.py paper-review --pretty >> /tmp/trading_ai_paper_review.log 2>&1
```

You can also snapshot the current simulated state on demand:

```bash
python cli.py paper-summary --pretty
```

Full paper-trading reports include the latest scheduled-job status, recent alert summary, severity
counts, failed-job count, and paper-cycle job status when those rows exist in SQLite.

## 12. Stress Testing And Scenario Simulation

Stress testing is deterministic and paper-trading-only. It simulates market, data-quality,
risk-control, and control-plane failures without calling live providers or placing orders.

Useful environment flags:

- `STRESS_TESTING_ENABLED=true`
- `STRESS_TEST_JOB_ENABLED=false`
- `STRESS_MAX_ACCEPTABLE_LOSS_R=3.0`
- `STRESS_BLOCK_ON_EXTREME_DATA_FAILURE=true`

List available scenarios:

```bash
python cli.py stress-scenarios --pretty
```

Run one scenario against a sample paper candidate:

```bash
python cli.py stress-test --scenario market_gap_down --pretty
```

Run the default stress suite:

```bash
python cli.py stress-suite --pretty
```

Stress currently open simulated paper trades in SQLite:

```bash
python cli.py portfolio-stress --scenario volatility_spike --pretty
```

Simulate data failures without provider calls:

```bash
python cli.py data-failure-sim --scenario provider_outage --pretty
```

The registered `stress_test` job is disabled by default and must be run explicitly:

```bash
python cli.py job-run --job stress_test --pretty
```

Stress tests can downgrade or block simulated recommendations, but they never make a rejected
candidate eligible and never unblock option recommendations.

## 13. Troubleshooting

### TWS Connection Refused

- Confirm Trader Workstation is open.
- Confirm ActiveX and Socket Clients are enabled.
- Confirm Read-Only API is enabled.
- Confirm `IBKR_HOST=127.0.0.1` and `IBKR_PORT=7496` match TWS.
- Run `.venv/bin/python cli.py ibkr-diagnose --ticker AAPL --pretty`.

### Option Quotes Unavailable

- Option metadata can work even when option quotes fail.
- IBKR error `10089` usually indicates market-data subscription or permission issues.
- OPRA/options quote permissions may be required.
- Final option recommendations should remain blocked until quote, IV, Greeks, DTE, spread, and fill gates pass.

### WMT Historical Timeout

- Treat as a provider/runtime data issue, not a trade signal.
- Re-run with a smaller universe or lower concurrency if rate limits/timeouts appear.
- Historical fallback warnings should be preserved in reports and scanner output.

### BRK.B Symbol Issue

- Provider symbol formats differ.
- IBKR may require class-share normalization such as `BRK B`.
- Use ticker normalization diagnostics and avoid manually forcing a trade when symbol mapping fails.

### Stale Or Fallback Data Warnings

- Historical-bar fallback may be acceptable for after-close swing scans.
- It is not suitable for intraday entries or precise option spread work.
- Candidates with stale/unavailable data should be blocked or downgraded by data-quality gates.

### Macro Critical Block

- Macro risk can block final recommendations around critical events.
- Run `.venv/bin/python cli.py macro-calendar --days 14 --pretty`.
- Run `.venv/bin/python cli.py macro-risk --pretty`.
- Do not override a critical macro block with Gemini narrative.

### Startup Readiness Blocked

- Run `.venv/bin/python cli.py config-check --pretty`.
- Run `.venv/bin/python cli.py readiness-check --pretty`.
- Fix blocking errors before running paper cycles.
- Missing optional API keys are warnings unless a feature is configured as required.

### DB Migration Issue

- Run `.venv/bin/python cli.py db-migrate --pretty`.
- Run `.venv/bin/python cli.py db-status --pretty`.
- SQLite database files are local artifacts and should not be committed.

### Audit Chain Issue

- Run `.venv/bin/python cli.py db-status --pretty`.
- Treat audit-chain failures as critical diagnostics.
- Do not edit audit rows by hand; investigate the source of corruption or regenerate a clean local test database if appropriate.

## 14. Notes

- `auto_log` defaults to `false` on the weekly trade hunt route.
- No route places real trades or sends brokerage orders.
- Paper-trading commands and jobs are simulated only and never place live orders.
- The CLI and jobs layer do not expose buy, sell, order, or execution commands.
- Scheduler support is intentionally externalized to `cron` or another job runner to avoid hidden background execution.
- `/predict/{ticker}` is a legacy route and may be unavailable if old model artifacts are missing.
