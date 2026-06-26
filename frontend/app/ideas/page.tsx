"use client";

import { useMemo, useState } from "react";
import { apiPost, ApiResult } from "@/lib/api";
import { Badge } from "@/components/Badge";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";
import { AssistantResultPanel } from "@/components/ideas/AssistantResultPanel";
import { AssistantTradeResponse, normalizeChatResponse } from "@/lib/tradingTypes";

const filters = ["All", "Paper eligible", "Stocks", "Options", "Watchlist", "Blocked"] as const;
type Filter = typeof filters[number];

function applyFilter(assistant: AssistantTradeResponse, filter: Filter): AssistantTradeResponse {
  if (filter === "All") return assistant;
  if (filter === "Paper eligible") {
    return {
      ...assistant,
      top_stocks: assistant.top_stocks.filter((row) => row.status.includes("paper_eligible")),
      top_options: assistant.top_options.filter((row) => row.status.includes("paper_eligible")),
      option_underlying_watchlist: [],
      paper_eligible: assistant.paper_eligible,
      research_only: [],
      blocked: []
    };
  }
  if (filter === "Stocks") {
    return { ...assistant, top_options: [], option_underlying_watchlist: [] };
  }
  if (filter === "Options") {
    return { ...assistant, top_stocks: [], paper_eligible: assistant.paper_eligible.filter((row) => row.asset_type === "option") };
  }
  if (filter === "Watchlist") {
    return {
      ...assistant,
      paper_eligible: [],
      top_stocks: assistant.top_stocks.filter((row) => row.status.toLowerCase().includes("watch")),
      top_options: assistant.top_options.filter((row) => row.status.toLowerCase().includes("research")),
      blocked: []
    };
  }
  return {
    ...assistant,
    paper_eligible: [],
    top_stocks: assistant.top_stocks.filter((row) => row.status.toLowerCase().includes("block")),
    top_options: assistant.top_options.filter((row) => row.status.toLowerCase().includes("block")),
    option_underlying_watchlist: [],
    research_only: []
  };
}

export default function IdeasPage() {
  const [result, setResult] = useState<ApiResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>("All");

  async function runFreshScan() {
    setLoading(true);
    const response = await apiPost("/api/scan", {
      universe: "mega_cap",
      max_tickers: 25,
      max_trades: 2,
      min_trades: 0,
      include_options: true,
      prefer_options: false,
      include_market_regime: true,
      include_relative_strength: true,
      include_portfolio_risk: true,
      include_position_sizing: true
    }, { timeoutMs: 120000 });
    setResult(response);
    setLoading(false);
  }

  const normalized = useMemo(() => {
    if (!result) return null;
    return normalizeChatResponse({
      ...result,
      answer: result.formatted_best_ideas_summary,
      mode: "ideas_scan"
    });
  }, [result]);
  const filteredAssistant = normalized ? applyFilter(normalized.assistant, filter) : null;

  return (
    <div>
      <PageHeader
        eyebrow="Ideas"
        title="Best available ideas"
        description="Run an explicit backend scan and review paper-eligible, watchlist, research-only, and blocked ideas without client-side scoring."
      />
      <WarningBox items={["This page uses backend ordering and deterministic statuses only.", "No auto-log, order, buy, sell, or brokerage request is sent."]} />

      <section className="mt-6 rounded-[2rem] border border-white/70 bg-white/75 p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-2xl font-black">Fresh scan</h2>
            <p className="mt-1 text-sm text-stone-600">Includes stock ideas and safe option research gates. Expensive scans only run when you press the button.</p>
          </div>
          <button
            className="rounded-2xl bg-ink px-5 py-3 font-black text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-tide"
            onClick={runFreshScan}
            disabled={loading}
            type="button"
          >
            {loading ? "Scanning..." : "Run a fresh scan"}
          </button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {filters.map((item) => (
            <button
              key={item}
              className={`rounded-full px-4 py-2 text-sm font-bold focus:outline-none focus:ring-2 focus:ring-tide ${filter === item ? "bg-ink text-white" : "bg-stone-100 text-stone-700"}`}
              onClick={() => setFilter(item)}
              type="button"
            >
              {item}
            </button>
          ))}
        </div>
      </section>

      {!result && !loading ? (
        <section className="mt-6 rounded-[2rem] border border-dashed border-stone-300 bg-white/55 p-8 text-center">
          <Badge tone="neutral">No scan loaded</Badge>
          <p className="mt-3 text-sm text-stone-600">Run a fresh scan to populate paper-eligible ideas, stock watchlist rows, exact option research, and blocked-but-interesting candidates.</p>
        </section>
      ) : null}

      {filteredAssistant && normalized ? (
        <section className="mt-6">
          <AssistantResultPanel response={normalized} assistant={filteredAssistant} raw={result} />
        </section>
      ) : null}
    </div>
  );
}
