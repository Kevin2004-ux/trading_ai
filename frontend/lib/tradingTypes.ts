export type UnknownRecord = Record<string, unknown>;

export interface ResearchSource {
  title: string;
  url: string;
  domain: string;
  sourceId?: string | number;
}

export interface MarketState {
  provider_status?: string;
  market_regime?: unknown;
  data_freshness?: unknown;
  partial_results?: boolean;
  message?: string | null;
}

export interface ScanSummary {
  run_id?: string | null;
  universe?: string | null;
  tickers_scanned?: number | null;
  profiles_run?: string[];
  include_options?: boolean;
  options_final_eligibility?: boolean;
  partial_results?: boolean;
}

export interface RefinementSummary {
  used?: boolean;
  passes_executed?: number;
  stop_reason?: string;
  changes?: string[];
  warnings?: string[];
}

export interface StockIdeaRow {
  ticker: string;
  asset_type: "stock";
  status: string;
  rank?: number | null;
  opportunity_score?: number | null;
  engine_score?: number | null;
  setup?: string | null;
  direction?: string | null;
  entry_price?: number | null;
  target_price?: number | null;
  stop_loss?: number | null;
  risk_reward?: number | null;
  why_ranked: string[];
  key_risks: string[];
  failed_constraints: string[];
  confirmation_needed: string[];
  data_quality?: unknown;
  research_status?: string;
  research_summary?: string | null;
  current_catalysts: string[];
  current_risks: string[];
  research_uncertainties: string[];
  research_source_ids: Array<string | number>;
  secondary_status_notes?: string[];
}

export interface OptionIdeaRow {
  ticker: string;
  asset_type: "option";
  status: string;
  rank?: number | null;
  opportunity_score?: number | null;
  engine_score?: number | null;
  strategy?: string | null;
  option_contract?: string | null;
  option_type?: string | null;
  strike?: number | null;
  expiration?: string | null;
  days_to_expiration?: number | null;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  spread_percent?: number | null;
  open_interest?: number | null;
  volume?: number | null;
  implied_volatility?: number | null;
  iv_rank?: number | null;
  delta?: number | null;
  breakeven_price?: number | null;
  underlying_status?: string | null;
  underlying_opportunity_score?: number | null;
  why_ranked: string[];
  key_risks: string[];
  missing_requirements: string[];
  research_status?: string;
  research_summary?: string | null;
  current_catalysts: string[];
  current_risks: string[];
  research_uncertainties: string[];
  research_source_ids: Array<string | number>;
}

export interface OptionUnderlyingRow {
  ticker: string;
  asset_type: "option_underlying";
  status: string;
  rank?: number | null;
  option_bias?: string | null;
  underlying_opportunity_score?: number | null;
  underlying_status?: string | null;
  why_watch: string[];
  required_before_contract_ranking: string[];
  research_status?: string;
  research_summary?: string | null;
  current_catalysts: string[];
  current_risks: string[];
  research_uncertainties: string[];
  research_source_ids: Array<string | number>;
}

export interface AssistantTradeResponse {
  ok?: boolean;
  response_type?: string;
  paper_trading_only?: boolean;
  ranking_status?: string;
  research_status?: string;
  research_sources: ResearchSource[];
  research_warnings: string[];
  requested_instrument?: string;
  market_state: MarketState;
  top_stocks: StockIdeaRow[];
  top_options: OptionIdeaRow[];
  option_underlying_watchlist: OptionUnderlyingRow[];
  option_discovery_status?: string;
  option_data_missing: string[];
  paper_eligible: Array<StockIdeaRow | OptionIdeaRow>;
  research_only: Array<StockIdeaRow | OptionIdeaRow>;
  blocked: Array<StockIdeaRow | OptionIdeaRow>;
  why_no_final_trades: string[];
  data_missing: string[];
  system_issues: string[];
  next_steps: string[];
  scan_summary: ScanSummary;
  refinement: RefinementSummary;
}

export interface BestAvailableIdeas {
  ok?: boolean;
  paper_trading_only?: boolean;
  summary?: string;
  ranking_status?: string;
  option_discovery_status?: string;
  options_final_eligibility?: boolean;
  paper_eligible?: UnknownRecord[];
  stock_watchlist?: UnknownRecord[];
  option_research_only?: UnknownRecord[];
  option_underlying_watchlist?: UnknownRecord[];
  blocked_but_interesting?: UnknownRecord[];
  why_no_final_trades?: string[];
  data_missing?: string[];
  option_data_missing?: string[];
  system_issues?: string[];
  next_steps?: string[];
  warnings?: string[];
}

export interface NormalizedChatResponse {
  ok: boolean;
  mode?: string;
  answer: string;
  gemini_available?: boolean;
  planner_provider?: string;
  planner_status?: string;
  planner_fallback_used?: boolean;
  validation_status?: string;
  warnings: string[];
  errors: string[];
  assistant: AssistantTradeResponse;
  bestIdeas: BestAvailableIdeas;
  raw: UnknownRecord;
}

export interface LearningStatusSummary {
  status?: string;
  active_policy_version?: string;
  candidate_snapshot_count?: number;
  mature_outcome_count?: number;
  pending_outcome_count?: number;
  walk_forward_ready?: boolean;
  promotion_ready?: boolean;
}

export function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function recordOf(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

export function arrayOfRecords(value: unknown): UnknownRecord[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function stringList(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "string") return [];
    const text = item.trim();
    return text ? [text] : [];
  });
}

export function idList(value: unknown): Array<string | number> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string | number => typeof item === "string" || typeof item === "number");
}

export function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function textOrNull(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text ? text : null;
}

export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function domainFromUrl(value: string): string {
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function sanitizeSources(value: unknown): ResearchSource[] {
  return arrayOfRecords(value).flatMap((source, index) => {
    const url = safeHttpUrl(source.url);
    if (!url) return [];
    const rawId = source.source_id ?? source.id;
    const sourceId = typeof rawId === "number" || typeof rawId === "string" ? rawId : undefined;
    return [{
      url,
      title: textOrNull(source.title) || textOrNull(source.domain) || `Source ${index + 1}`,
      domain: textOrNull(source.domain) || domainFromUrl(url),
      sourceId
    }];
  });
}

function normalizeStock(row: UnknownRecord, fallbackStatus = "watchlist", fallbackRank?: number): StockIdeaRow {
  return {
    ticker: String(row.ticker ?? "").toUpperCase() || "UNKNOWN",
    asset_type: "stock",
    status: String(row.status ?? row.recommendation_status ?? fallbackStatus),
    rank: numberOrNull(row.rank) ?? fallbackRank ?? null,
    opportunity_score: numberOrNull(row.opportunity_score ?? row.idea_score),
    engine_score: numberOrNull(row.engine_score ?? row.score),
    setup: textOrNull(row.setup ?? row.setup_type ?? row.scan_profile),
    direction: textOrNull(row.direction),
    entry_price: numberOrNull(row.entry_price),
    target_price: numberOrNull(row.target_price),
    stop_loss: numberOrNull(row.stop_loss),
    risk_reward: numberOrNull(row.risk_reward),
    why_ranked: stringList(row.why_ranked ?? row.reason ?? row.thesis),
    key_risks: stringList(row.key_risks ?? row.rejection_reason ?? row.invalidation),
    failed_constraints: stringList(row.failed_constraints),
    confirmation_needed: stringList(row.confirmation_needed),
    data_quality: row.data_quality,
    research_status: textOrNull(row.research_status) || undefined,
    research_summary: textOrNull(row.research_summary),
    current_catalysts: stringList(row.current_catalysts),
    current_risks: stringList(row.current_risks),
    research_uncertainties: stringList(row.research_uncertainties),
    research_source_ids: idList(row.research_source_ids)
  };
}

function normalizeOption(row: UnknownRecord, fallbackStatus = "research_only", fallbackRank?: number): OptionIdeaRow {
  return {
    ticker: String(row.ticker ?? "").toUpperCase() || "UNKNOWN",
    asset_type: "option",
    status: String(row.status ?? row.recommendation_status ?? fallbackStatus),
    rank: numberOrNull(row.rank) ?? fallbackRank ?? null,
    opportunity_score: numberOrNull(row.opportunity_score ?? row.option_opportunity_score ?? row.idea_score),
    engine_score: numberOrNull(row.engine_score ?? row.score),
    strategy: textOrNull(row.strategy ?? row.strategy_type),
    option_contract: textOrNull(row.option_contract ?? row.contract),
    option_type: textOrNull(row.option_type),
    strike: numberOrNull(row.strike),
    expiration: textOrNull(row.expiration),
    days_to_expiration: numberOrNull(row.days_to_expiration ?? row.dte),
    bid: numberOrNull(row.bid),
    ask: numberOrNull(row.ask),
    mid: numberOrNull(row.mid),
    spread_percent: numberOrNull(row.spread_percent),
    open_interest: numberOrNull(row.open_interest),
    volume: numberOrNull(row.volume),
    implied_volatility: numberOrNull(row.implied_volatility ?? row.iv),
    iv_rank: numberOrNull(row.iv_rank),
    delta: numberOrNull(row.delta),
    breakeven_price: numberOrNull(row.breakeven_price ?? row.breakeven),
    underlying_status: textOrNull(row.underlying_status),
    underlying_opportunity_score: numberOrNull(row.underlying_opportunity_score),
    why_ranked: stringList(row.why_ranked ?? row.reason ?? row.selection_reason),
    key_risks: stringList(row.key_risks ?? row.rejection_reason),
    missing_requirements: stringList(row.missing_requirements),
    research_status: textOrNull(row.research_status) || undefined,
    research_summary: textOrNull(row.research_summary),
    current_catalysts: stringList(row.current_catalysts),
    current_risks: stringList(row.current_risks),
    research_uncertainties: stringList(row.research_uncertainties),
    research_source_ids: idList(row.research_source_ids)
  };
}

function normalizeUnderlying(row: UnknownRecord, fallbackRank?: number): OptionUnderlyingRow {
  return {
    ticker: String(row.ticker ?? "").toUpperCase() || "UNKNOWN",
    asset_type: "option_underlying",
    status: String(row.status ?? "watchlist"),
    rank: numberOrNull(row.rank) ?? fallbackRank ?? null,
    option_bias: textOrNull(row.option_bias),
    underlying_opportunity_score: numberOrNull(row.underlying_opportunity_score),
    underlying_status: textOrNull(row.underlying_status),
    why_watch: stringList(row.why_watch ?? row.why_ranked ?? row.reason),
    required_before_contract_ranking: stringList(row.required_before_contract_ranking ?? row.missing_requirements),
    research_status: textOrNull(row.research_status) || undefined,
    research_summary: textOrNull(row.research_summary),
    current_catalysts: stringList(row.current_catalysts),
    current_risks: stringList(row.current_risks),
    research_uncertainties: stringList(row.research_uncertainties),
    research_source_ids: idList(row.research_source_ids)
  };
}

export function normalizeAssistantResponse(payload: unknown): AssistantTradeResponse {
  const root = recordOf(payload);
  const scanSummary = recordOf(root.scan_summary);
  const refinement = recordOf(root.refinement);
  const topStocks = arrayOfRecords(root.top_stocks).map((row, index) => normalizeStock(row, "watchlist", index + 1));
  const topOptions = arrayOfRecords(root.top_options).map((row, index) => normalizeOption(row, "research_only", index + 1));
  const underlyings = arrayOfRecords(root.option_underlying_watchlist).map((row, index) => normalizeUnderlying(row, index + 1));
  return {
    ok: Boolean(root.ok ?? true),
    response_type: textOrNull(root.response_type) || undefined,
    paper_trading_only: root.paper_trading_only !== false,
    ranking_status: textOrNull(root.ranking_status) || "no_qualifying_ideas",
    research_status: textOrNull(root.research_status) || undefined,
    research_sources: sanitizeSources(root.research_sources),
    research_warnings: stringList(root.research_warnings),
    requested_instrument: textOrNull(root.requested_instrument) || undefined,
    market_state: recordOf(root.market_state),
    top_stocks: topStocks,
    top_options: topOptions,
    option_underlying_watchlist: underlyings,
    option_discovery_status: textOrNull(root.option_discovery_status) || undefined,
    option_data_missing: stringList(root.option_data_missing),
    paper_eligible: arrayOfRecords(root.paper_eligible).map((row, index) => {
      return String(row.asset_type ?? "").toLowerCase() === "option" ? normalizeOption(row, "paper_eligible", index + 1) : normalizeStock(row, "paper_eligible", index + 1);
    }),
    research_only: arrayOfRecords(root.research_only).map((row, index) => {
      return String(row.asset_type ?? "").toLowerCase() === "option" ? normalizeOption(row, "research_only", index + 1) : normalizeStock(row, "watchlist", index + 1);
    }),
    blocked: arrayOfRecords(root.blocked).map((row, index) => {
      return String(row.asset_type ?? "").toLowerCase() === "option" ? normalizeOption(row, "blocked", index + 1) : normalizeStock(row, "blocked", index + 1);
    }),
    why_no_final_trades: stringList(root.why_no_final_trades),
    data_missing: stringList(root.data_missing),
    system_issues: stringList(root.system_issues),
    next_steps: stringList(root.next_steps),
    scan_summary: {
      run_id: textOrNull(scanSummary.run_id),
      universe: textOrNull(scanSummary.universe),
      tickers_scanned: numberOrNull(scanSummary.tickers_scanned),
      profiles_run: stringList(scanSummary.profiles_run),
      include_options: Boolean(scanSummary.include_options),
      options_final_eligibility: Boolean(scanSummary.options_final_eligibility),
      partial_results: Boolean(scanSummary.partial_results)
    },
    refinement: {
      used: Boolean(refinement.used),
      passes_executed: numberOrNull(refinement.passes_executed) ?? 1,
      stop_reason: textOrNull(refinement.stop_reason) || "",
      changes: stringList(refinement.changes),
      warnings: stringList(refinement.warnings)
    }
  };
}

export function normalizeChatResponse(payload: unknown): NormalizedChatResponse {
  const root = recordOf(payload);
  const assistantPayload = Object.keys(recordOf(root.assistant_response)).length
    ? root.assistant_response
    : buildAssistantFromBestIdeas(root);
  const validation = recordOf(root.validation);
  return {
    ok: root.ok !== false,
    mode: textOrNull(root.mode) || undefined,
    answer: textOrNull(root.answer) || textOrNull(root.formatted_best_ideas_summary) || textOrNull(root.error) || "No response text was returned.",
    gemini_available: typeof root.gemini_available === "boolean" ? root.gemini_available : undefined,
    planner_provider: textOrNull(root.planner_provider) || undefined,
    planner_status: textOrNull(root.planner_status) || undefined,
    planner_fallback_used: typeof root.planner_fallback_used === "boolean" ? root.planner_fallback_used : undefined,
    validation_status: textOrNull(validation.validation_status) || undefined,
    warnings: stringList(root.warnings),
    errors: stringList(root.errors ?? root.error),
    assistant: normalizeAssistantResponse(assistantPayload),
    bestIdeas: recordOf(root.best_available_ideas) as BestAvailableIdeas,
    raw: root
  };
}

function buildAssistantFromBestIdeas(root: UnknownRecord): UnknownRecord {
  const best = recordOf(root.best_available_ideas);
  return {
    ok: root.ok,
    paper_trading_only: root.paper_trading_only,
    ranking_status: best.ranking_status,
    top_stocks: arrayOfRecords(best.paper_eligible)
      .filter((row) => String(row.asset_type ?? "stock").toLowerCase() !== "option")
      .concat(arrayOfRecords(best.stock_watchlist), arrayOfRecords(best.blocked_but_interesting).filter((row) => String(row.asset_type ?? "stock").toLowerCase() !== "option")),
    top_options: arrayOfRecords(best.option_research_only)
      .concat(arrayOfRecords(best.blocked_but_interesting).filter((row) => String(row.asset_type ?? "").toLowerCase() === "option")),
    option_underlying_watchlist: arrayOfRecords(best.option_underlying_watchlist),
    paper_eligible: arrayOfRecords(best.paper_eligible),
    why_no_final_trades: best.why_no_final_trades,
    data_missing: best.data_missing,
    system_issues: best.system_issues,
    next_steps: best.next_steps,
    option_data_missing: best.option_data_missing,
    option_discovery_status: best.option_discovery_status,
    research_sources: [],
    market_state: {
      provider_status: best.ranking_status === "unavailable" ? "unavailable" : "unknown",
      message: best.ranking_status === "unavailable" ? "Ranking unavailable because usable market data was not returned." : null
    },
    scan_summary: recordOf(root.summary),
    refinement: recordOf(root.refinement)
  };
}

export function learningSummary(value: unknown): LearningStatusSummary {
  const row = recordOf(value);
  return {
    status: textOrNull(row.status) || undefined,
    active_policy_version: textOrNull(row.active_policy_version) || undefined,
    candidate_snapshot_count: numberOrNull(row.candidate_snapshot_count) ?? undefined,
    mature_outcome_count: numberOrNull(row.mature_outcome_count) ?? undefined,
    pending_outcome_count: numberOrNull(row.pending_outcome_count) ?? undefined,
    walk_forward_ready: typeof row.walk_forward_ready === "boolean" ? row.walk_forward_ready : undefined,
    promotion_ready: typeof row.promotion_ready === "boolean" ? row.promotion_ready : undefined
  };
}
