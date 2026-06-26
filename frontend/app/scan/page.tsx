"use client";

import { useMemo, useState } from "react";
import { apiPost, ApiResult } from "@/lib/api";
import { normalizeChatResponse } from "@/lib/tradingTypes";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";
import { AssistantResultPanel } from "@/components/ideas/AssistantResultPanel";

export default function ScanPage() {
  const [form, setForm] = useState({
    universe: "mega_cap",
    max_tickers: 25,
    max_trades: 2,
    include_options: false,
    include_market_regime: true,
    include_relative_strength: true,
    include_portfolio_risk: true,
    include_position_sizing: true
  });
  const [result, setResult] = useState<ApiResult | null>(null);
  const [loading, setLoading] = useState(false);

  function update(key: string, value: unknown) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function runScan() {
    setLoading(true);
    setResult(await apiPost("/api/scan", { ...form, min_trades: 0, prefer_options: false }, { timeoutMs: 120000 }));
    setLoading(false);
  }

  const normalized = useMemo(() => {
    if (!result) return null;
    return normalizeChatResponse({
      ...result,
      answer: result.formatted_best_ideas_summary,
      mode: "scan_page"
    });
  }, [result]);

  return (
    <div>
      <PageHeader
        eyebrow="Advanced scan"
        title="Run a deterministic scan"
        description="Manual paper-cycle controls for explicit backend scans. Chat and Ideas are the primary experience; this page keeps engineering controls available."
      />
      <WarningBox items={["The frontend never sends auto_log=true.", "Options remain research-only or blocked unless backend quote, IV, Greeks, liquidity, spread, and fill-quality gates pass."]} />

      <section className="grid gap-4 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-3">
        <label className="text-sm font-bold">Universe
          <select className="mt-2 w-full rounded-xl border p-3 focus:outline-none focus:ring-2 focus:ring-tide" value={form.universe} onChange={(e) => update("universe", e.target.value)}>
            <option value="mega_cap">mega_cap</option>
            <option value="large_cap">large_cap</option>
            <option value="custom">custom</option>
          </select>
        </label>
        <label className="text-sm font-bold">Max tickers
          <input className="mt-2 w-full rounded-xl border p-3 focus:outline-none focus:ring-2 focus:ring-tide" type="number" value={form.max_tickers} onChange={(e) => update("max_tickers", Number(e.target.value))} />
        </label>
        <label className="text-sm font-bold">Max paper trades
          <input className="mt-2 w-full rounded-xl border p-3 focus:outline-none focus:ring-2 focus:ring-tide" type="number" value={form.max_trades} onChange={(e) => update("max_trades", Number(e.target.value))} />
        </label>
        {[
          ["include_options", "Include options research"],
          ["include_market_regime", "Market regime"],
          ["include_relative_strength", "Relative strength"],
          ["include_portfolio_risk", "Portfolio risk"],
          ["include_position_sizing", "Position sizing"]
        ].map(([key, label]) => (
          <label key={key} className="flex items-center gap-3 rounded-2xl bg-stone-50 p-3 text-sm font-bold">
            <input type="checkbox" checked={Boolean(form[key as keyof typeof form])} onChange={(e) => update(key, e.target.checked)} />
            {label}
          </label>
        ))}
        <button className="rounded-2xl bg-ink px-5 py-3 font-black text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-tide md:col-span-3" disabled={loading} onClick={runScan} type="button">
          {loading ? "Running scan..." : "Run fresh scan"}
        </button>
      </section>

      {normalized ? (
        <>
          <section className="mt-6 grid gap-4 md:grid-cols-4">
            <Card title="Ranking" value={<Badge>{normalized.assistant.ranking_status}</Badge>} />
            <Card title="Paper eligible" value={normalized.assistant.paper_eligible.length} />
            <Card title="Stocks" value={normalized.assistant.top_stocks.length} />
            <Card title="Options" value={normalized.assistant.top_options.length + normalized.assistant.option_underlying_watchlist.length} />
          </section>
          <section className="mt-6">
            <AssistantResultPanel response={normalized} assistant={normalized.assistant} raw={result} />
          </section>
        </>
      ) : null}
    </div>
  );
}
