"use client";

import { useState } from "react";
import { apiPost, asList, asRecord, pickNested } from "@/lib/api";
import { fmt, fmtPrice } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

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
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  function update(key: string, value: unknown) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function runScan() {
    setLoading(true);
    setResult(await apiPost("/api/scan", { ...form, min_trades: 0, prefer_options: false }));
    setLoading(false);
  }

  const summary = asRecord(result?.summary);
  const decision = asRecord(result?.decision_result);
  const selection = asRecord(result?.selection_result);
  const scanResult = asRecord(result?.scan_result);
  const finalTrades = asList(decision.final_recommendations ?? result?.paper_trades_logged);
  const watchlist = asList(selection.watchlist_alternatives);
  const rejected = asList(selection.rejected_candidates).concat(asList(decision.risk_rejected), asList(decision.not_selected));
  const warnings = [
    ...((Array.isArray(result?.warnings) ? result?.warnings : []) as string[]),
    ...((Array.isArray(pickNested(scanResult, "data_quality_summary.warnings")) ? pickNested(scanResult, "data_quality_summary.warnings") : []) as string[])
  ];

  return (
    <div>
      <PageHeader eyebrow="Run scan" title="Best paper picks" description="Runs the backend paper-cycle path. It can log simulated paper trades, but it never places brokerage orders." />
      <section className="grid gap-4 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-3">
        <label className="text-sm font-bold">Universe
          <select className="mt-2 w-full rounded-xl border p-3" value={form.universe} onChange={(e) => update("universe", e.target.value)}>
            <option value="mega_cap">mega_cap</option>
            <option value="large_cap">large_cap</option>
            <option value="custom">custom</option>
          </select>
        </label>
        <label className="text-sm font-bold">Max tickers
          <input className="mt-2 w-full rounded-xl border p-3" type="number" value={form.max_tickers} onChange={(e) => update("max_tickers", Number(e.target.value))} />
        </label>
        <label className="text-sm font-bold">Max trades
          <input className="mt-2 w-full rounded-xl border p-3" type="number" value={form.max_trades} onChange={(e) => update("max_trades", Number(e.target.value))} />
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
        <button className="rounded-2xl bg-ink px-5 py-3 font-black text-white disabled:opacity-50 md:col-span-3" disabled={loading} onClick={runScan} type="button">
          {loading ? "Running deterministic scan..." : "Run paper scan"}
        </button>
      </section>

      {result ? (
        <>
          <section className="mt-6 grid gap-4 md:grid-cols-4">
            <Card title="Selected" value={fmt(summary.selected_count, String(finalTrades.length))} />
            <Card title="Logged" value={fmt(summary.logged_count, "0")} />
            <Card title="Failed tickers" value={fmt(pickNested(scanResult, "scan_execution_summary.failed_tickers.length"), "0")} />
            <Card title="Options" value={<Badge>{form.include_options ? "Research gated" : "Stock only"}</Badge>} />
          </section>
          <div className="mt-6">
            <WarningBox title="Scan warnings and blocks" items={warnings.concat(finalTrades.length ? [] : ["No final paper trades were selected."])} />
          </div>
          <TradeBucket title="Final paper trades" rows={finalTrades} />
          <TradeBucket title="Watchlist" rows={watchlist} />
          <TradeBucket title="Rejected or risk-blocked" rows={rejected} />
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <Card title="Macro / regime" detail={fmt(JSON.stringify(result.macro_risk ?? result.market_regime ?? {}))} />
            <Card title="Scan execution" detail={fmt(JSON.stringify(scanResult.scan_execution_summary ?? {}))} />
          </div>
          <div className="mt-6"><JsonPanel data={result} /></div>
        </>
      ) : null}
    </div>
  );
}

function TradeBucket({ title, rows }: { title: string; rows: Record<string, unknown>[] }) {
  return (
    <section className="mt-6 rounded-3xl bg-white/75 p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-2xl font-black">{title}</h2>
        <Badge tone={rows.length ? "good" : "neutral"}>{rows.length}</Badge>
      </div>
      {rows.length ? (
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Ticker</th><th>Status</th><th>Entry</th><th>Target</th><th>Stop</th><th>Reason</th></tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.ticker}-${index}`}>
                  <td className="font-black">{fmt(row.ticker)}</td>
                  <td><Badge>{fmt(row.recommendation_status ?? row.status ?? row.outcome ?? "paper")}</Badge></td>
                  <td>{fmtPrice(row.entry_price)}</td>
                  <td>{fmtPrice(row.target_price)}</td>
                  <td>{fmtPrice(row.stop_loss)}</td>
                  <td>{fmt(row.rejection_reason ?? row.reason ?? row.thesis ?? row.invalidation)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="text-sm text-stone-600">No rows returned.</p>}
    </section>
  );
}
