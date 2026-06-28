# Trading AI Build Roadmap

This roadmap turns the current master outline into an implementation plan that fits the existing codebase.

Goal:

Build a stronger trading assistant that always returns the best safe ideas available, expands candidate discovery beyond static universes, and keeps AI influence inside controlled planning lanes without weakening deterministic safety.

## Product Direction

The target system is not an autonomous trading bot. It is a paper-trading research assistant with:

- dynamic idea discovery
- progressive validation under time limits
- best-available outputs instead of empty scans
- clearer user-facing reasoning
- strict feature provenance and provider-awareness

Core rule:

AI can help decide what to inspect next, how to explain results, and how to broaden soft search behavior. AI cannot bypass deterministic trade eligibility, data freshness, option quote rules, portfolio risk, or paper-only restrictions.

## Current System Fit

The repo already has the right foundation for this roadmap:

- `planning/ai_planner.py`, `planning/scan_plan.py`, and `planning/policy_validator.py` already provide AI plan proposal plus safety clamping.
- `planning/plan_executor.py` already executes approved plans and assembles `best_available_ideas`.
- `agent/trading_brain.py`, `scanner/swing_scanner.py`, and `selector/weekly_selector.py` already handle deterministic stock validation and selection.
- `ideas/best_ideas.py` and `ideas/assistant_response.py` already support `paper_eligible`, `stock_watchlist`, `blocked_but_interesting`, and option research buckets.
- `research/`, `providers/`, `realtime/`, `quality/`, and `risk/` already contain most of the signal and safety layers we need to preserve.
- `frontend/` already has a chat/dashboard surface where result clarity improvements can land immediately.

Because of that, the next step should be an extension plan, not a rewrite.

## Implementation Principles

- Preserve paper-only behavior.
- Preserve deterministic eligibility gates.
- Prefer partial results over null results when market data is partially available.
- Separate discovery score from trade score.
- Track what data was known at decision time.
- Make provider limitations explicit to both planner and UI.

## Phase 0: Immediate Cleanup

### 0.1 Frontend result cleanup

Primary goal:

Make outputs easier to trust and easier to scan.

Likely files:

- `frontend/lib/tradingTypes.ts`
- `frontend/components/ideas/AssistantResultPanel.tsx`
- `frontend/components/ideas/StockIdeaCard.tsx`
- `frontend/components/ideas/OptionIdeaCard.tsx`
- `frontend/components/ideas/IdeaStatusBadge.tsx`
- `frontend/components/ideas/ResearchSources.tsx`
- `frontend/app/chat/page.tsx`

Tasks:

- Deduplicate repeated tickers across watchlist and blocked buckets before rendering cards.
- Show one canonical card per ticker with secondary status notes when the same symbol appears in multiple profiles.
- Hide option sections for stock-only requests.
- Improve badge contrast and wording for `watchlist`, `blocked`, `research_only`, and `paper_eligible`.
- Keep raw JSON collapsed by default and move warnings higher in the layout.

Acceptance criteria:

- A stock-only review never renders empty option panels.
- A ticker shown in multiple buckets appears once as a main card.
- Warnings and near-miss explanations are readable without opening JSON.

### 0.2 Broad-scan behavior fix

Primary goal:

Avoid returning “nothing” when some valid results were already found.

Likely files:

- `planning/plan_executor.py`
- `planning/refinement_controller.py`
- `ideas/best_ideas.py`
- `ideas/assistant_response.py`
- `ui/app.py`

Tasks:

- Treat partial candidate validation as a usable success path.
- Only emit `ranking_unavailable` when no legitimate candidate data survived.
- Return valid ranked buckets even if one provider, one refinement pass, or one universe load failed.
- Distinguish between `no ideas passed` and `data failed`.

Acceptance criteria:

- “Give me your best stocks” can return watchlist or blocked-but-interesting ideas after partial scanner success.
- `ranking_unavailable` only appears on true end-to-end candidate failure.

## Phase 1: Dynamic Discovery And Always-Return Ideas

This is the highest-priority build phase.

### 1.1 Candidate discovery engine

Primary goal:

Create a discovery layer before deterministic validation so we search smarter than static universes alone.

New package:

```text
discovery/
  __init__.py
  candidate_discovery.py
  source_models.py
  fallback_universe.py
  trend_sources.py
  news_sources.py
  social_sources.py
```

Integration points:

- `planning/plan_executor.py`
- `planning/refinement_controller.py`
- `scanner/universe_builder.py`
- `research/news_provider.py`
- `analytics/relative_strength.py`
- `market/calendar.py`
- `tracking/trade_logger.py` or a new snapshot table in `db/`

Sources to support in priority order:

1. recent scanner and watchlist candidates
2. liquid fallback universe
3. market movers and relative-volume names
4. news and catalyst names
5. earnings names
6. sector leaders
7. database candidate snapshots
8. social or trending sources when available

Notes:

- Start with internal and provider-backed sources already represented in the repo.
- Make social and Yahoo-style trending optional adapters, not hard dependencies.

### 1.2 Discovery candidate model

Primary goal:

Represent why a ticker deserves validation without confusing that with final trade quality.

Suggested model fields:

- `ticker`
- `source`
- `source_type`
- `discovered_at`
- `as_of`
- `discovery_score`
- `reason_discovered`
- `warnings`
- `raw_metadata`
- `point_in_time_safe`
- `requires_live_validation`

Recommended location:

- `discovery/source_models.py`

Important rule:

`discovery_score` ranks what to validate next. It must not be reused as `opportunity_score` or trade eligibility.

### 1.3 Progressive validation

Primary goal:

Use time-budgeted rounds so the system can stop early and still return the strongest validated names.

Implementation direction:

- Discovery builds a ranked pool of candidate tickers.
- `plan_executor` validates the top batch first.
- If paper-eligible or watchlist coverage is too weak, expand into the next batch.
- Stop before timeout or policy limit and return the best validated output.

Suggested execution fields:

- `discovered_count`
- `validated_rounds`
- `validated_ticker_count`
- `partial_results`
- `stopped_reason`

Likely files:

- `planning/plan_executor.py`
- `planning/refinement_controller.py`
- `agent/trading_brain.py`

Acceptance criteria:

- A large request can stop after early rounds and still return ranked ideas.
- The system prefers hot discovered names before static filler symbols.
- Timeout pressure degrades breadth before it degrades usefulness.

### 1.4 Always-return output logic

Primary goal:

Return the strongest safe output bucket available whenever market data works.

Canonical output buckets:

1. final paper-eligible trades
2. watchlist ideas
3. research-only ideas
4. blocked but interesting ideas
5. provider or data issue explanation

Likely files:

- `ideas/best_ideas.py`
- `ideas/assistant_response.py`
- `ideas/idea_formatter.py`
- `frontend/lib/tradingTypes.ts`

Acceptance criteria:

- If no paper trades pass, the assistant still returns best watchlist or research ideas.
- “No ideas” is only used when the data path truly failed.
- UI and API consistently separate near-miss ideas from provider failures.

## Phase 2: AI Planner Upgrades

### 2.1 Let AI control discovery, not safety

Primary goal:

Allow the planner to steer soft search behavior while keeping hard safety fixed.

AI may adjust:

- discovery source mix
- discovery breadth
- focus on momentum, oversold, catalysts, or relative volume
- watchlist depth
- display thresholds
- related ticker expansion

AI may not adjust:

- hard price or freshness rules
- risk/reward minimums
- option quote, IV, Greeks, or spread requirements
- portfolio risk
- brokerage execution
- auto-logging eligibility

Likely files:

- `planning/scan_plan.py`
- `planning/ai_planner.py`
- `planning/policy_validator.py`
- `planning/planner_prompts.py`

### 2.2 ScanPlan fields to add

Recommended fields:

- `use_dynamic_discovery`
- `discovery_sources`
- `max_discovered_tickers`
- `validation_rounds`
- `minimum_display_score`
- `return_best_available`
- `hot_topic_focus`
- `news_focus`
- `social_focus`
- `catalyst_focus`

Validation requirements:

- `PolicyValidator` clamps all numeric limits.
- Unsupported sources are removed rather than failing the entire plan.
- Safety-sensitive fields remain immutable.

Acceptance criteria:

- AI can ask for “focus on catalyst names” or “broaden discovery” and receive approved soft adjustments.
- The approved plan never changes deterministic eligibility rules.

## Phase 3: Feature Provenance And Provider Capability Tracking

This phase should land before any major advanced-signal expansion.

### 3.1 Feature registry

Primary goal:

Know exactly what data and signals were available when a decision was made.

New package:

```text
features/
  registry.py
  models.py
```

Each feature record should track:

- `feature_name`
- `feature_version`
- `source`
- `as_of`
- `retrieved_at`
- `freshness_seconds`
- `point_in_time_safe`
- `coverage_status`
- `warnings`
- `errors`

Integration points:

- `realtime/market_data.py`
- `realtime/features.py`
- `feature_store/`
- `research/`
- `options/`
- `analytics/`

Acceptance criteria:

- A ranked idea can explain which features were present, stale, missing, or blocked.
- Future-data leakage risks are auditable.

### 3.2 Provider capability registry

Primary goal:

Let the planner and UI reason from actual provider reachability instead of assumptions.

Recommended file:

- `providers/capabilities.py`

Capability examples:

- stock quotes
- historical bars
- market movers
- news source
- social source
- SEC access
- option chains
- option bid/ask
- IV
- Greeks
- open interest
- MOC imbalance
- corporate actions
- earnings calendar

Integration points:

- `providers/market_data_provider.py`
- `providers/options_data_provider.py`
- `config/runtime_readiness.py`
- `diagnostics/healthcheck.py`
- `planning/ai_planner.py`
- `ui/app.py`

Acceptance criteria:

- The planner does not request unavailable provider features when the system already knows they are missing.
- The UI can say “options blocked because quote capability is unavailable” instead of showing a vague failure.

## Recommended Delivery Order

1. Phase 0 cleanup so current outputs become clearer immediately.
2. Phase 1 discovery engine with internal sources first.
3. Phase 1 progressive validation and always-return logic.
4. Phase 2 planner-field expansion and policy clamping.
5. Phase 3 feature registry and provider capability registry.

This order improves user experience early, then improves idea quality, then strengthens explainability and system self-awareness.

## Testing Strategy

Backend tests to add:

- discovery ranking and source deduplication
- progressive validation stops and partial-result behavior
- `ranking_unavailable` edge cases
- planner clamp behavior for new discovery fields
- provider capability fallback behavior
- feature provenance completeness on returned ideas

Frontend tests to add:

- single-card render for duplicated tickers
- stock-only request hides option sections
- warning readability and status-badge rendering
- best-available fallback render when no paper trades pass

Likely test files:

- `tests/test_plan_executor.py`
- `tests/test_ai_planner.py`
- `tests/test_policy_validator.py`
- `tests/test_assistant_response.py`
- `tests/test_ui_routes.py`
- new discovery-specific tests such as `tests/test_candidate_discovery.py`

## First Concrete Milestone

If we want the fastest path to visible progress, the first implementation slice should be:

1. dedupe and clarify frontend result cards
2. fix partial-result handling so broad scans do not collapse to empty
3. add a minimal discovery layer using existing internal sources:
   recent watchlist names, fallback universe, relative-volume names, and current news or catalyst names when available

That milestone gets us from “sometimes empty and confusing” to “useful, explainable, and increasingly adaptive.”
