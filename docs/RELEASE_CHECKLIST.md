# Release Checklist

Use this checklist before cutting or pushing a local release. Keep environment-dependent items unchecked until they are verified in the target environment.

## Automated Tests

- [ ] Run the full offline Python test suite.
- [ ] Confirm there are no unexpected failures, skips, or new warnings.
- [ ] Record the exact test command and result in the release notes.

## Frontend Build/Lint

- [ ] Run the frontend type/lint command.
- [ ] Run the frontend production build.
- [ ] Confirm generated UI routes render without build-time errors.

## Database Backup And Migration

- [ ] Back up the current SQLite database before applying migrations.
- [ ] Run pending migrations against the target database.
- [ ] Verify schema status reports the latest migration version.
- [ ] Confirm audit-chain and migration status checks pass.

## TWS/IBKR Read-Only Verification

- [ ] Confirm TWS or IB Gateway is running.
- [ ] Confirm API socket clients are enabled.
- [ ] Confirm read-only API mode is enabled.
- [ ] Confirm localhost-only access is enabled.
- [ ] Run the read-only IBKR connectivity diagnostic.

## Stock Data Verification

- [ ] Verify stock quote snapshots work for representative tickers.
- [ ] Verify historical daily bars return usable OHLCV data.
- [ ] Confirm data freshness is market-calendar aware.
- [ ] Confirm fallback data is clearly labeled when used.

## Options Quote/OPRA Readiness

- [ ] Verify option-chain metadata is available.
- [ ] Verify option quote snapshots are available.
- [ ] Verify bid, ask, mid, IV, Greeks, liquidity, spread, and fill-quality fields are present.
- [ ] Confirm final option recommendations remain blocked when quote or OPRA data is unavailable.

## OpenAI Planner Optional Verification

- [ ] If enabled, verify the OpenAI planner proposes a ScanPlan only.
- [ ] Confirm `PolicyValidator` clamps unsafe or unsupported planner output.
- [ ] Confirm deterministic fallback works when OpenAI is unavailable.

## Current Research/Source Citation Verification

- [ ] If enabled, run current research on representative tickers.
- [ ] Confirm sources are returned with usable citations.
- [ ] Confirm research does not change ranking, eligibility, or hard constraints.

## SEC_USER_AGENT Verification

- [ ] If SEC research is enabled, confirm `SEC_USER_AGENT` is configured.
- [ ] Confirm SEC research is disabled or returns a clean unavailable status when `SEC_USER_AGENT` is missing.
- [ ] Confirm no personal contact details are committed to the repository.

## Deterministic Fallback Verification

- [ ] Disable or omit optional AI keys in a local test shell.
- [ ] Confirm chat best-ideas requests still run deterministic scan/fallback flows.
- [ ] Confirm the response explains unavailable AI providers without failing the app.

## Paper-Only Route Safety Audit

- [ ] Enumerate FastAPI routes.
- [ ] Confirm no buy, sell, order, or brokerage execution routes exist.
- [ ] Confirm scan/chat/planning execution paths use `auto_log=false` unless explicitly paper-logging through guardrails.
- [ ] Confirm blocked, watchlist, research-only, and data-failure ideas cannot be logged as final recommendations.

## Learning Status Verification

- [ ] Verify learning status endpoint or CLI command loads without errors.
- [ ] Confirm learning snapshots are observational.
- [ ] Confirm shadow-policy scoring does not alter visible ranking or log trades.

## Manual-Only Policy Promotion

- [ ] Confirm policy promotion requires explicit confirmation.
- [ ] Confirm promotion requires approver, approval reason, eligible proposal, and expected active policy version.
- [ ] Confirm promotion writes an audit event.
- [ ] Confirm chat cannot promote policies.

## Secret Scan

- [ ] Search for committed API keys, tokens, passwords, account identifiers, and personal contact data.
- [ ] Confirm `.env` is not committed.
- [ ] Confirm examples use safe placeholders only.

## Git Diff Review

- [ ] Run whitespace/conflict-marker checks.
- [ ] Review tracked modified files.
- [ ] Review untracked files.
- [ ] Confirm no accidental generated artifacts, caches, local databases, or debug files are included.
- [ ] Confirm the diff matches the release scope.

## Commit And Push

- [ ] Stage only intended files.
- [ ] Commit with a clear release message.
- [ ] Push the intended branch.
- [ ] Confirm no unrelated work was included.

## Post-Push Status Check

- [ ] Confirm the remote branch contains the expected commit.
- [ ] Confirm CI or remote checks start successfully.
- [ ] Review any failed checks before merging or tagging.
- [ ] Confirm release notes mention known optional-provider limitations.
