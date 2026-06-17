# Safety Policy

Trading AI is paper-trading and research software. It must not place real brokerage orders.

## Hard Boundaries

- No real buy orders.
- No real sell orders.
- No brokerage order routes.
- No order-transmission helpers.
- No `placeOrder` execution path.
- IBKR connectivity is read-only market data and diagnostics only.

If a user asks the app or LLM to buy, sell, or place an order, the system should refuse execution and explain that only simulated paper tracking is supported.

## Paper Trading Only

Paper recommendations are simulated records stored in SQLite. Simulated fills, slippage, stops, targets, outcomes, reports, and performance summaries are not brokerage activity and should not be treated as realized P/L.

SQLite is authoritative for:

- Paper recommendation records.
- Candidate evaluations.
- Scanner runs.
- Outcomes.
- Trade journal reviews.
- Audit/checkpoint history.
- Alert/job history.

## IBKR Read-Only

IBKR settings should keep:

```bash
IBKR_READ_ONLY=true
```

Trader Workstation should also have Read-Only API enabled and localhost-only access. Diagnostics may connect to TWS for quotes, historical bars, option metadata, or option quote checks, but they must not create orders.

## Deterministic Gates Are Source Of Truth

The system decides candidate eligibility through objective rules and structured data, not narrative judgment.

- Gemini can explain or summarize deterministic outputs.
- Gemini cannot override failed constraints.
- Gemini cannot log unsafe trades directly.
- Memory can provide qualitative context only.
- Pinecone memory cannot override hard gates.
- Human annotations can inform review, but do not bypass constraints.

## Options Safety

Final option recommendations remain blocked unless deterministic gates pass, including:

- Option quote availability.
- IV rank/context.
- Greeks quality.
- Days-to-expiration checks.
- Spread/fill quality.
- Risk/reward and max-loss checks.
- Strategy gating.

If IBKR option metadata works but option quotes are unavailable, options must remain research-only or blocked.

## Data-Quality Safety

Data-quality gates should block or downgrade candidates when:

- Provider data is unavailable.
- Latest bars are stale.
- Quote data is missing and historical fallback is not appropriate.
- Partial scan results were used.
- Ticker normalization failed.
- Intraday-sensitive decisions only have daily close fallback data.

Historical-bar fallback can be acceptable for after-close swing scans, but it is not suitable for precise intraday entries.

## Stress Testing

Stress tests are simulations, not guarantees. They can:

- Downgrade a candidate.
- Block new simulated trades.
- Surface data-quality/control-plane failures.
- Estimate portfolio stress loss.

Stress tests cannot:

- Make a rejected candidate eligible.
- Unblock option candidates.
- Replace live risk management.
- Guarantee real future outcomes.

## Alerts

Alerts are local/SQLite by default. External delivery should only occur when explicitly configured. Alerts do not place trades, close trades, or change brokerage state.
