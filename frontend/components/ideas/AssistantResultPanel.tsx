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
    : `stock:${row.ticker}:${row.setup || ""}:${row.status}`;
}

function isPaperEligible(row: StockIdeaRow | OptionIdeaRow): boolean {
  return row.status.toLowerCase().includes("paper_eligible") || row.status.toLowerCase().includes("recommendable");
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
  const finalCount = assistant.paper_eligible.length || [...assistant.top_stocks, ...assistant.top_options].filter(isPaperEligible).length;
  const stockCount = assistant.top_stocks.filter((row) => !isPaperEligible(row)).length;
  const optionCount = assistant.top_options.filter((row) => !isPaperEligible(row)).length;
  const underlyingCount = assistant.option_underlying_watchlist.length;
  const passes = assistant.refinement.passes_executed || 1;
  const rankingUnavailable = assistant.ranking_status === "unavailable";
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
          : `${finalCount} final paper trades · ${stockCount} stock ideas · ${optionCount} exact option ideas · ${underlyingCount} option underlyings · ${passes} scan pass${passes === 1 ? "" : "es"}`}
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
  const eligible = assistant.paper_eligible.length
    ? assistant.paper_eligible
    : [...assistant.top_stocks, ...assistant.top_options].filter(isPaperEligible);
  const eligibleKeys = new Set(eligible.map(keyFor));
  const stockRows = rankingUnavailable ? [] : assistant.top_stocks.filter((row) => !eligibleKeys.has(keyFor(row)) && !isPaperEligible(row));
  const optionRows = rankingUnavailable ? [] : assistant.top_options.filter((row) => !eligibleKeys.has(keyFor(row)) && !isPaperEligible(row));
  const underlyings = rankingUnavailable ? [] : assistant.option_underlying_watchlist;
  const paperStockRows = eligible.filter((row): row is StockIdeaRow => row.asset_type === "stock");
  const paperOptionRows = eligible.filter((row): row is OptionIdeaRow => row.asset_type === "option");
  const sources: ResearchSource[] = assistant.research_sources;
  const warnings = [...extraWarnings, ...assistant.research_warnings, ...assistant.option_data_missing].filter(Boolean);
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

      {!rankingUnavailable && eligible.length ? (
        <Section title="Final paper-eligible ideas" count={eligible.length}>
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

      {!rankingUnavailable ? (
        <Section title="Best exact option ideas" count={optionRows.length}>
          {optionRows.length ? <div className="space-y-4">{optionRows.map((idea) => <OptionIdeaCard key={keyFor(idea)} idea={idea} sources={sources} />)}</div> : <p className="text-sm text-stone-600">No exact option contracts qualified. Option quotes, IV, Greeks, spread, liquidity, or fill quality may be missing.</p>}
        </Section>
      ) : null}

      {!rankingUnavailable ? (
        <Section title="Option-underlying watchlist" count={underlyings.length}>
          {underlyings.length ? <div className="space-y-4">{underlyings.map((idea) => <OptionUnderlyingCard key={idea.ticker} idea={idea} sources={sources} />)}</div> : <p className="text-sm text-stone-600">No underlying-only option watchlist rows returned.</p>}
        </Section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <TextList title="Why no final paper trades" items={assistant.why_no_final_trades} />
        <TextList title="Data missing" items={assistant.data_missing} />
        <TextList title="System issues" items={assistant.system_issues} />
      </div>

      <Section title="Research evidence and sources" count={sources.length}>
        {sources.length ? <ResearchSources sources={sources} compact={false} /> : <p className="text-sm text-stone-600">No current research sources were attached to this response.</p>}
      </Section>

      <RefinementSummary refinement={assistant.refinement} scanSummary={assistant.scan_summary} />

      <div className="grid gap-4 lg:grid-cols-2">
        <TextList title="Warnings" items={[...warnings, ...(response?.warnings || [])]} />
        <TextList title="Next steps" items={assistant.next_steps} />
      </div>

      <section className="rounded-3xl border border-stone-200 bg-white/50 p-4">
        <h3 className="mb-3 text-lg font-black">Advanced diagnostics</h3>
        <JsonPanel title="Raw backend payload" data={raw ?? response?.raw} />
      </section>
    </div>
  );
}
