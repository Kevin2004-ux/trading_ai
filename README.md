# Trading AI

Trading AI is a chat-first, paper-trading-only research assistant for stock swing ideas and research-only option ideas. It combines deterministic scanners, strict safety gates, SQLite audit records, optional AI planning/explanation, and a Next.js dashboard.

The system is designed to surface useful best-available ideas without letting the AI approve trades. Deterministic rules, data-quality checks, and SQLite records remain the source of truth.

## Safety

- No real order placement is implemented or exposed.
- IBKR/TWS support is read-only market data and diagnostics only.
- The planner proposes a `ScanPlan`; `PolicyValidator` and deterministic gates decide what can run.
- Research and AI explanations cannot change candidate ranking, eligibility, hard constraints, or outcomes.
- Options stay research-only/blocked unless option quotes, IV, Greeks, spreads, and fill quality are available.
- Learning snapshots and shadow policies are observational until a manual policy-promotion path is explicitly used.
- Paper logging goes through existing guardrails and must not log watchlist, blocked, or data-failure ideas as trades.

## Architecture

```text
user chat/dashboard
-> intent/planner or deterministic fallback
-> proposed ScanPlan
-> PolicyValidator
-> adaptive or single-pass executor
-> deterministic scanner/trading brain
-> stock opportunity ranker
-> independent option discovery when requested
-> option opportunity ranker
-> source-grounded research when requested
-> assistant response formatter
-> frontend cards
-> learning snapshot recorder
-> SQLite audit/trade/performance tables
```

Key directories:

- `ui/`: FastAPI app, API bridge, and route handlers.
- `frontend/`: Next.js chat-first dashboard.
- `planning/`: AI/deterministic ScanPlan proposal, policy validation, adaptive execution, and refinement.
- `agent/`, `scanner/`, `selector/`: trading-brain orchestration, multi-profile scanning, and selection.
- `ideas/`, `options/`, `research/`: best-ideas formatting, option discovery/ranking, and source-grounded research.
- `tracking/`, `db/`, `journal/`, `learning/`: SQLite records, migrations, outcomes, policy snapshots, and learning reports.
- `providers/`, `realtime/`, `quality/`, `risk/`, `macro/`: data providers, freshness/quality, risk gates, and regime checks.

## Requirements

- Python 3.12 or newer.
- Node.js 20 LTS or newer and npm for the dashboard.
- SQLite, included with Python on normal local installs.
- TWS or IB Gateway only if you want IBKR read-only market data.
- Market-data permissions for whichever provider you choose.
- Optional keys for OpenAI planning/research, Gemini compatibility, Polygon/FMP data, SEC research, and Pinecone semantic memory.

Missing AI keys should not block local startup; the backend uses deterministic fallback and returns clean unavailable statuses.

## Install

```bash
cd /Users/kevinfrederick/trading_ai
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Install the dashboard dependencies:

```bash
cd /Users/kevinfrederick/trading_ai/frontend
npm install
cp .env.example .env.local
```

The frontend default is:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Configure

Use `.env.example` as the source of safe local defaults. The default configuration is paper-only and IBKR read-only:

```env
MARKET_DATA_PROVIDER=ibkr
OPTIONS_DATA_PROVIDER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=123
IBKR_READ_ONLY=true
IBKR_USE_DELAYED_DATA=true
ALLOW_OPTIONS_WITHOUT_QUOTES=false
ENABLE_OPTIONS=false
```

Optional keys:

- `OPENAI_API_KEY`: optional AI ScanPlan proposal, refinement, and current web research.
- `GEMINI_API_KEY`: optional compatibility chat/narration path.
- `POLYGON_API_KEY`: optional Polygon market/options data.
- `FMP_API_KEY`: optional news/earnings provider.
- `SEC_USER_AGENT`: required only when `SEC_RESEARCH_ENABLED=true`.
- `PINECONE_API_KEY` and `PINECONE_INDEX_NAME`: optional semantic memory; SQLite remains the source of truth.

## IBKR/TWS

In Trader Workstation or IB Gateway:

- Enable ActiveX and Socket Clients.
- Enable Read-Only API.
- Allow localhost only.
- Match the socket port in `.env`, commonly `7496` for live TWS.

IBKR may provide stock historical bars and quotes while option quotes remain unavailable without OPRA/options permissions. That is expected: stock-only scans can still run when safe, while final option recommendations remain blocked.

## Run Backend

```bash
cd /Users/kevinfrederick/trading_ai
source .venv/bin/activate
.venv/bin/python -m uvicorn ui.app:app --host 127.0.0.1 --port 8000 --reload
```

Smoke checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/status
```

## Run Frontend

```bash
cd /Users/kevinfrederick/trading_ai/frontend
npm run dev
```

Open `http://localhost:3000`. The dashboard uses the FastAPI backend for scans, chat, trades, system diagnostics, and learning views.

## Validate Local Release

Run offline backend tests:

```bash
cd /Users/kevinfrederick/trading_ai
.venv/bin/python -m pytest -q
```

Run frontend checks:

```bash
cd /Users/kevinfrederick/trading_ai/frontend
npm run lint
npm run build
```

Run configuration diagnostics:

```bash
cd /Users/kevinfrederick/trading_ai
.venv/bin/python cli.py config-check --pretty
.venv/bin/python cli.py readiness-check --pretty
.venv/bin/python cli.py db-status --pretty
```

Run provider dry-runs only when you expect local provider connectivity:

```bash
.venv/bin/python cli.py live-dry-run --ticker AAPL --pretty
.venv/bin/python cli.py ibkr-diagnose --ticker AAPL --pretty
.venv/bin/python cli.py ibkr-options-diagnose --ticker AAPL --pretty
```

## Common Local Commands

Stock-only paper cycle:

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

Review paper portfolio:

```bash
.venv/bin/python cli.py paper-review --pretty
.venv/bin/python cli.py paper-summary --pretty
```

Generate reports:

```bash
.venv/bin/python cli.py report --type full_paper_trading --format markdown --pretty
```

## API Route Groups

- Read-only status/diagnostics: `/`, `/health`, `/api/status`, `/api/frontend-debug`, `/api/readiness`, `/api/db-status`, `/diagnostics/environment`, `/diagnostics/live-dry-run`, `/api/system/*`.
- Research and scan execution: `/api/chat`, `/api/scan`, `/api/options/strategies`, `/api/options/discover`, `/api/planning/*`, `/api/research/current`, `/predict/{ticker}`, `/ask`.
- Paper-trade history and performance: `/api/trades`, `/api/trades/{recommendation_id}`, `/api/performance`, `/trades/open`, `/trades/performance`, `/trades/update-outcomes`, `/paper/*`, `/journal/*`, `/reports/*`.
- Learning/evaluation: `/api/learning/status`, `/api/learning/grade-outcomes`, `/api/learning/evaluate-policy`, `/api/learning/proposals`, `/api/learning/policies`.
- Manual policy governance: `/api/learning/promote`, which is explicit and separate from chat.
- Legacy compatibility routes: `/brain/*`, `/trades/*`, `/paper/*`, `/reports/*`, `/journal/*`.

No route should place brokerage orders. If a route touches market data or IBKR-backed sync code, it is bridged through the backend API helper so the app can safely run from FastAPI worker threads.

## Troubleshooting

- If chat says an AI provider is unavailable, deterministic scan/planning can still run.
- If stock-only scans fail because TWS is unreachable, restore IBKR/TWS or switch providers and rerun.
- If option quotes are unavailable, final option recommendations remain blocked; research-only option ideas may still explain what data is missing.
- If the database schema is missing, run the migration command exposed by `cli.py` or rerun startup diagnostics to initialize local SQLite.
- If frontend calls fail, confirm the backend is on port `8000` and `NEXT_PUBLIC_API_BASE_URL` points to it.

More detail lives in:

- `docs/RUNBOOK.md`
- `docs/ARCHITECTURE.md`
- `docs/SAFETY.md`
- `docs/CLI_REFERENCE.md`
