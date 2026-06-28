import { Badge } from "@/components/Badge";
import { JsonPanel } from "@/components/JsonPanel";
import { WarningBox } from "@/components/WarningBox";
import { fmt } from "@/lib/format";
import {
  AssistantTradeResponse,
  NormalizedChatResponse,
  OptionIdeaRow,
  ResearchSource,
  StockIdeaRow
} from "@/lib/tradingTypes";
import { OptionIdeaCard } from "./OptionIdeaCard";
import { OptionUnderlyingCard } from "./OptionUnderlyingCard";
import { RefinementSummary } from "./RefinementSummary";
import { ResearchSources } from "./ResearchSources";
import { StockIdeaCard } from "./StockIdeaCard";
import type { ReactNode } from "react";

function keyFor(row: StockIdeaRow | OptionIdeaRow): string {
  return row.asset_type === "option"
    ? `option:${row.option_contract || row.ticker}:${row.status}`
    : `stock:${row.ticker}`;
}

function isPaperEligible(row: StockIdeaRow | OptionIdeaRow): boolean {
  const normalized = row.status.toLowerCase();
  return normalized.includes("paper_eligible") || normalized.includes("paper eligible") || normalized.includes("recommendable");
}

function statusLabel(status: string | null | undefined): string {
  const normalized = String(status || "").toLowerCase();
  if (normalized.includes("paper_eligible") || normalized.includes("paper eligible") || normalized.includes("recommendable")) return "Paper eligible";
  if (normalized.includes("watch")) return "Watchlist";
  if (normalized.includes("research_only") || normalized.includes("research only")) return "Research only";
  if (normalized.includes("block") || normalized.includes("reject") || normalized.includes("fail")) return "Blocked";
  return fmt(status, "Unknown status");
}

function statusPriority(status: string | null | undefined): number {
  const label = statusLabel(status);
  if (label === "Paper eligible") return 4;
  if (label === "Watchlist") return 3;
  if (label === "Research only") return 2;
  if (label === "Blocked") return 1;
  return 0;
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const text = String(value || "").trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueIds(values: Array<string | number>): Array<string | number> {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = String(value);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function duplicateNote(row: StockIdeaRow): string {
  const parts = [statusLabel(row.status)];
  if (row.setup) parts.push(row.setup);
  if (row.rank !== null && row.rank !== undefined) parts.push(`#${row.rank}`);
  if (row.failed_constraints.length) parts.push(`${row.failed_constraints.length} failed constraint${row.failed_constraints.length === 1 ? "" : "s"}`);
  if (row.confirmation_needed.length) parts.push(`${row.confirmation_needed.length} confirmation item${row.confirmation_needed.length === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

function cloneStockRow(row: StockIdeaRow): StockIdeaRow {
  return {
    ...row,
    why_ranked: [...row.why_ranked],
    key_risks: [...row.key_risks],
    failed_constraints: [...row.failed_constraints],
    confirmation_needed: [...row.confirmation_needed],
    current_catalysts: [...row.current_catalysts],
    current_risks: [...row.current_risks],
    research_uncertainties: [...row.research_uncertainties],
    research_source_ids: [...row.research_source_ids],
    secondary_status_notes: [...(row.secondary_status_notes || [])]
  };
}

function mergeStockDetails(primary: StockIdeaRow, duplicate: StockIdeaRow): StockIdeaRow {
  return {
    ...primary,
    why_ranked: uniqueStrings([...primary.why_ranked, ...duplicate.why_ranked]),
    key_risks: uniqueStrings([...primary.key_risks, ...duplicate.key_risks]),
    failed_constraints: uniqueStrings([...primary.failed_constraints, ...duplicate.failed_constraints]),
    confirmation_needed: uniqueStrings([...primary.confirmation_needed, ...duplicate.confirmation_needed]),
    current_catalysts: uniqueStrings([...primary.current_catalysts, ...duplicate.current_catalysts]),
    current_risks: uniqueStrings([...primary.current_risks, ...duplicate.current_risks]),
    research_uncertainties: uniqueStrings([...primary.research_uncertainties, ...duplicate.research_uncertainties]),
    research_source_ids: uniqueIds([...primary.research_source_ids, ...duplicate.research_source_ids]),
    secondary_status_notes: uniqueStrings([...(primary.secondary_status_notes || []), duplicateNote(duplicate), ...(duplicate.secondary_status_notes || [])])
  };
}

function shouldReplaceStock(current: StockIdeaRow, incoming: StockIdeaRow): boolean {
  const currentPriority = statusPriority(current.status);
  const incomingPriority = statusPriority(incoming.status);
  if (incomingPriority !== currentPriority) return incomingPriority > currentPriority;
  const currentRank = current.rank ?? Number.POSITIVE_INFINITY;
  const incomingRank = incoming.rank ?? Number.POSITIVE_INFINITY;
  return incomingRank < currentRank;
}

function dedupeStockRows(rows: StockIdeaRow[]): StockIdeaRow[] {
  const byTicker = new Map<string, StockIdeaRow>();
  for (const row of rows) {
    const ticker = row.ticker.toUpperCase();
    if (!ticker) continue;
    const incoming = cloneStockRow(row);
    const current = byTicker.get(ticker);
    if (!current) {
      byTicker.set(ticker, incoming);
      continue;
    }
    if (shouldReplaceStock(current, incoming)) {
      byTicker.set(ticker, mergeStockDetails(incoming, current));
    } else {
      byTicker.set(ticker, mergeStockDetails(current, incoming));
    }
  }
  return [...byTicker.values()].sort((left, right) => {
    const priorityDiff = statusPriority(right.status) - statusPriority(left.status);
    if (priorityDiff) return priorityDiff;
    return (left.rank ?? Number.POSITIVE_INFINITY) - (right.rank ?? Number.POSITIVE_INFINITY);
  });
}

function optionsRequested(assistant: AssistantTradeResponse): boolean {
  const requested = String(assistant.requested_instrument || "").toLowerCase();
  if (requested === "stocks") return false;
  if (requested === "options" || requested === "both") return true;
  return Boolean(assistant.scan_summary.include_options || assistant.top_options.length || assistant.option_underlying_watchlist.length);
}

function Section({
  title,
  count,
  children
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[1.8rem] bg-white/55 p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-2xl font-black text-ink">{title}</h3>
        {count !== undefined ? <Badge tone={count ? "research" : "neutral"}>{count}</Badge> : null}
      </div>
      {children}
    </section>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <WarningBox title={title} items={items.slice(0, 8)} />
  );
}

export function ResultSummary({ assistant }: { assistant: AssistantTradeResponse }) {
  const showOptions = optionsRequested(assistant);
  const eligibleRows = assistant.paper_eligible.length
    ? assistant.paper_eligible
    : [...assistant.top_stocks, ...(showOptions ? assistant.top_options : [])].filter(isPaperEligible);
  const finalStockCount = dedupeStockRows(eligibleRows.filter((row): row is StockIdeaRow => row.asset_type === "stock")).length;
  const finalOptionCount = showOptions ? eligibleRows.filter((row) => row.asset_type === "option").length : 0;
  const finalCount = finalStockCount + finalOptionCount;
  const stockCount = dedupeStockRows(assistant.top_stocks.filter((row) => !isPaperEligible(row))).length;
  const optionCount = showOptions ? assistant.top_options.filter((row) => !isPaperEligible(row)).length : 0;
  const underlyingCount = showOptions ? assistant.option_underlying_watchlist.length : 0;
  const passes = assistant.refinement.passes_executed || 1;
  const rankingUnavailable = assistant.ranking_status === "unavailable";
  const countParts = [
    `${finalCount} final paper trades`,
    `${stockCount} stock ideas`,
    ...(showOptions ? [`${optionCount} exact option ideas`, `${underlyingCount} option underlyings`] : []),
    `${passes} scan pass${passes === 1 ? "" : "es"}`
  ];
  return (
    <div className="rounded-[1.6rem] border border-white/70 bg-ink p-5 text-white shadow-card">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={rankingUnavailable ? "blocked" : assistant.ranking_status === "available" ? "good" : "warning"}>
          {rankingUnavailable ? "Market ranking unavailable" : fmt(assistant.ranking_status, "ranking unknown")}
        </Badge>
        <Badge tone="neutral">{assistant.paper_trading_only === false ? "Safety check" : "Paper trading only"}</Badge>
        <Badge tone={assistant.market_state.provider_status === "available" ? "good" : assistant.market_state.provider_status === "unavailable" ? "blocked" : "research"}>
          Provider {fmt(assistant.market_state.provider_status, "unknown")}
        </Badge>
      </div>
      <p className="mt-4 text-2xl font-black leading-tight">
        {rankingUnavailable
          ? "Market ranking unavailable"
          : countParts.join(" · ")}
      </p>
      {assistant.market_state.message ? <p className="mt-2 text-sm text-stone-200">{assistant.market_state.message}</p> : null}
    </div>
  );
}

export function AssistantResultPanel({
  response,
  assistant,
  raw,
  extraWarnings = []
}: {
  response?: NormalizedChatResponse;
  assistant: AssistantTradeResponse;
  raw?: unknown;
  extraWarnings?: string[];
}) {
  const rankingUnavailable = assistant.ranking_status === "unavailable";
  const showOptions = optionsRequested(assistant);
  const eligible = assistant.paper_eligible.length
    ? assistant.paper_eligible
    : [...assistant.top_stocks, ...(showOptions ? assistant.top_options : [])].filter(isPaperEligible);
  const eligibleKeys = new Set(eligible.filter((row) => row.asset_type === "option").map(keyFor));
  const optionRows = rankingUnavailable || !showOptions ? [] : assistant.top_options.filter((row) => !eligibleKeys.has(keyFor(row)) && !isPaperEligible(row));
  const underlyings = rankingUnavailable || !showOptions ? [] : assistant.option_underlying_watchlist;
  const stockPool = rankingUnavailable
    ? []
    : [
        ...eligible.filter((row): row is StockIdeaRow => row.asset_type === "stock"),
        ...assistant.top_stocks.filter((row) => !isPaperEligible(row))
      ];
  const dedupedStocks = dedupeStockRows(stockPool);
  const paperStockRows = dedupedStocks.filter(isPaperEligible);
  const stockRows = dedupedStocks.filter((row) => !isPaperEligible(row));
  const paperOptionRows = showOptions ? eligible.filter((row): row is OptionIdeaRow => row.asset_type === "option") : [];
  const finalCount = paperStockRows.length + paperOptionRows.length;
  const sources: ResearchSource[] = assistant.research_sources;
  const warnings = [...extraWarnings, ...assistant.research_warnings, ...(showOptions ? assistant.option_data_missing : [])].filter(Boolean);
  return (
    <div className="space-y-5">
      <ResultSummary assistant={assistant} />

      {rankingUnavailable ? (
        <WarningBox
          title="Provider or market-data issue"
          items={[
            ...(assistant.system_issues.length ? assistant.system_issues : []),
            ...(assistant.data_missing.length ? assistant.data_missing : []),
            ...(assistant.system_issues.length || assistant.data_missing.length ? [] : ["Usable market data was not returned, so the frontend did not render ticker cards."])
          ]}
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <TextList title="Why no final paper trades" items={assistant.why_no_final_trades} />
        <TextList title="Data missing" items={assistant.data_missing} />
        <TextList title="System issues" items={assistant.system_issues} />
        <TextList title="Warnings" items={[...warnings, ...(response?.warnings || [])]} />
      </div>

      {!rankingUnavailable && finalCount ? (
        <Section title="Final paper-eligible ideas" count={finalCount}>
          <div className="space-y-4">
            {paperStockRows.map((idea) => <StockIdeaCard key={keyFor(idea)} idea={idea} sources={sources} />)}
            {paperOptionRows.map((idea) => <OptionIdeaCard key={keyFor(idea)} idea={idea} sources={sources} />)}
          </div>
        </Section>
      ) : null}

      {!rankingUnavailable ? (
        <Section title="Best stock ideas" count={stockRows.length}>
          {stockRows.length ? <div className="space-y-4">{stockRows.map((idea) => <StockIdeaCard key={keyFor(idea)} idea={idea} sources={sources} />)}</div> : <p className="text-sm text-stone-600">No stock ideas qualified for display.</p>}
        </Section>
      ) : null}

      {!rankingUnavailable && showOptions ? (
        <Section title="Best exact option ideas" count={optionRows.length}>
          {optionRows.length ? <div className="space-y-4">{optionRows.map((idea) => <OptionIdeaCard key={keyFor(idea)} idea={idea} sources={sources} />)}</div> : <p className="text-sm text-stone-600">No exact option contracts qualified. Option quotes, IV, Greeks, spread, liquidity, or fill quality may be missing.</p>}
        </Section>
      ) : null}

      {!rankingUnavailable && showOptions ? (
        <Section title="Option-underlying watchlist" count={underlyings.length}>
          {underlyings.length ? <div className="space-y-4">{underlyings.map((idea) => <OptionUnderlyingCard key={idea.ticker} idea={idea} sources={sources} />)}</div> : <p className="text-sm text-stone-600">No underlying-only option watchlist rows returned.</p>}
        </Section>
      ) : null}

      <Section title="Research evidence and sources" count={sources.length}>
        {sources.length ? <ResearchSources sources={sources} compact={false} /> : <p className="text-sm text-stone-600">No current research sources were attached to this response.</p>}
      </Section>

      <RefinementSummary refinement={assistant.refinement} scanSummary={assistant.scan_summary} />

      <div className="grid gap-4 lg:grid-cols-2">
        <TextList title="Next steps" items={assistant.next_steps} />
      </div>

      <section className="rounded-3xl border border-stone-200 bg-white/50 p-4">
        <h3 className="mb-3 text-lg font-black">Advanced diagnostics</h3>
        <JsonPanel title="Raw backend payload" data={raw ?? response?.raw} />
      </section>
    </div>
  );
}
