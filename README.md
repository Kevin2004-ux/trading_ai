# Trading AI

Trading AI is a deterministic, paper-trading research system for swing-trade candidate discovery, risk gating, paper logging, diagnostics, and reporting. The LLM layer is optional and explanatory only; structured rules, SQLite records, and deterministic gates remain the source of truth.

This project does not place real trades. It does not expose buy, sell, order, or brokerage execution routes. IBKR support is read-only market-data connectivity.

## What It Does

- Builds stock and research-only option candidates from recent market data.
- Applies data-quality, macro, market-regime, technical, concentration, position-sizing, options, memory, and research-risk gates.
- Logs simulated paper recommendations and outcomes to SQLite.
- Produces performance attribution, strategy diagnostics, reports, alerts, and stress-test summaries.
- Provides FastAPI routes, CLI commands, and manual scheduled-job workflows.

## Architecture

High-level flow:

```text
startup readiness
-> manual CLI / FastAPI / scheduled job runner
-> trading brain
-> async scanner
-> data quality and provider routing
-> technical, macro, research, options, memory, and portfolio-risk gates
-> candidate ranking and simulated fill/slippage
-> paper logger, checkpoints, and audit log
-> reports, alerts, stress tests, and performance analytics
```

Key directories:

- `agent/`: trading brain orchestration.
- `scanner/`, `selector/`, `pipeline/`: universe scanning, async execution, and weekly selection.
- `realtime/`, `providers/`, `data_ingest/`: market/options data access and provider adapters.
- `risk/`, `quality/`, `macro/`, `options/`, `research/`, `memory/`: deterministic gating subsystems.
- `tracking/`, `db/`, `journal/`: SQLite trade records, migrations, audit/checkpoints, and reviews.
- `reports/`, `alerts/`, `simulation/`, `analytics/`: diagnostics and feedback loops.
- `ui/`: FastAPI app and dashboard routes.
- `cli.py`: operational command entrypoint.

See `docs/ARCHITECTURE.md` for a fuller subsystem map.

## Setup

Use Python 3.12 or newer.

```bash
cd /Users/kevinfrederick/trading_ai
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Optional environment variables:

- `GEMINI_API_KEY`: optional chat/narration.
- `POLYGON_API_KEY`: optional Polygon market/options data.
- `FMP_API_KEY`: optional news/earnings transcript provider.
- `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`: optional semantic memory.
- `SEC_USER_AGENT`: required only when SEC research is enabled.

SQLite remains the source of truth for trades, outcomes, audit history, and deterministic records.

## IBKR/TWS Read-Only Setup

In Trader Workstation:

- Enable ActiveX and Socket Clients.
- Enable Read-Only API.
- Use socket port `7496` for live TWS or your configured paper/read-only port.
- Allow localhost only.

Recommended `.env` values:

```bash
MARKET_DATA_PROVIDER=ibkr
OPTIONS_DATA_PROVIDER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=123
IBKR_READ_ONLY=true
IBKR_USE_DELAYED_DATA=true
```

IBKR stock quotes and historical bars may work while option quotes remain unavailable unless OPRA/options permissions are active. Final option recommendations stay blocked unless quote, IV, Greeks, risk, and fill gates pass.

## Tests And Diagnostics

Run the full offline suite:

```bash
.venv/bin/python -m pytest -q
```

Run local readiness checks:

```bash
.venv/bin/python cli.py config-check --pretty
.venv/bin/python cli.py readiness-check --pretty
.venv/bin/python cli.py db-status --pretty
```

Run safe diagnostics:

```bash
.venv/bin/python cli.py live-dry-run --ticker AAPL --pretty
.venv/bin/python cli.py validate-gemini-output --sample weekly-trade-hunt --pretty
.venv/bin/python cli.py stress-suite --pretty
```

Manual IBKR diagnostics, only when TWS is open:

```bash
.venv/bin/python cli.py ibkr-diagnose --ticker AAPL --pretty
.venv/bin/python cli.py ibkr-options-diagnose --ticker AAPL --pretty
```

## Paper Trading

Stock-only paper cycle example:

```bash
.venv/bin/python cli.py paper-cycle \
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

This logs simulated paper trades only when deterministic gates pass. It does not place brokerage orders.

## Scheduled Jobs And Alerts

Jobs are registered but not automatically started on import. Run them explicitly:

```bash
.venv/bin/python cli.py jobs --pretty
.venv/bin/python cli.py job-run --job stress_test --pretty
.venv/bin/python cli.py alerts --pretty
```

Alerts are local/SQLite by default. External delivery requires explicit configuration.

## More Documentation

- `docs/RUNBOOK.md`: operations and troubleshooting.
- `docs/SAFETY.md`: safety boundaries and guardrails.
- `docs/ARCHITECTURE.md`: subsystem map and deterministic flow.
- `docs/CLI_REFERENCE.md`: command overview.
