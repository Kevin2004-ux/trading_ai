"use client";

import { useState } from "react";
import { apiPost, asList, asRecord } from "@/lib/api";
import { fmt, fmtPrice } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

export default function OptionsPage() {
  const [ticker, setTicker] = useState("AAPL");
  const [strategy, setStrategy] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    setResult(await apiPost("/api/options/strategies", { ticker, strategy: strategy || null }));
    setLoading(false);
  }

  const strategyResult = asRecord(result?.strategy_result);
  const rows = asList(strategyResult.strategies);
  const warnings = Array.isArray(result?.warnings) ? (result?.warnings as string[]) : [];
  const errors = Array.isArray(result?.errors) ? (result?.errors as string[]) : [];
  const optionPayloadText = JSON.stringify(result ?? {});
  const twsUnreachable = optionPayloadText.includes("Connect call failed") || optionPayloadText.includes("ConnectionRefusedError") || optionPayloadText.includes("127.0.0.1");

  return (
    <div>
      <PageHeader eyebrow="Options research" title="Gated options lab" description="Displays backend option strategy research. Blocked options are not recommendations." />
      <WarningBox items={["Options remain research-only or blocked unless every backend option gate passes.", "No option order placement exists in this frontend."]} />
      <section className="mt-6 grid gap-3 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-3">
        <input className="rounded-xl border p-3" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="Ticker" />
        <select className="rounded-xl border p-3" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="">All strategies</option>
          <option value="long_call">Long call</option>
          <option value="long_put">Long put</option>
          <option value="bull_call_debit_spread">Bull call debit spread</option>
          <option value="bear_put_debit_spread">Bear put debit spread</option>
        </select>
        <button className="rounded-xl bg-ink px-4 py-3 font-bold text-white disabled:opacity-50" disabled={loading} onClick={run} type="button">
          {loading ? "Checking..." : "Run option strategies check"}
        </button>
      </section>
      {result ? (
        <>
          {twsUnreachable ? (
            <div className="mt-6">
              <WarningBox
                title="IBKR/TWS unavailable"
                items={[
                  "IBKR/TWS is not reachable on 127.0.0.1:7496. Option contracts cannot be evaluated yet.",
                  "Research-only option ideas require option chain, bid/ask, IV, Greeks, and fill quality."
                ]}
              />
            </div>
          ) : null}
          <div className="mt-6"><WarningBox title="Option warnings" items={warnings} /></div>
          <div className="mt-4"><WarningBox title="Option errors / blocked reasons" items={errors} /></div>
          <section className="mt-6 rounded-3xl bg-white/75 p-5 shadow-card">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-black">Strategy candidates</h2>
              <Badge tone={result.ok ? "research" : "blocked"}>{result.ok ? "research output" : "blocked / unavailable"}</Badge>
            </div>
            {!rows.length ? (
              <div className="rounded-2xl border border-stone-200 bg-stone-50 p-4 text-sm text-stone-700">
                No option strategies are currently displayable. This is usually expected when option quotes are unavailable, OPRA permissions are missing, or the backend gates block the chain. No recommendation was created.
              </div>
            ) : null}
            <div className="table-shell">
              <table className="data-table">
                <thead><tr><th>Strategy</th><th>Status</th><th>Bid/ask</th><th>IV rank</th><th>Greeks</th><th>DTE</th><th>Why blocked/research-only</th></tr></thead>
                <tbody>
                  {rows.map((row, index) => {
                    const risk = asRecord(row.option_trade_risk);
                    const iv = asRecord(row.iv_context);
                    const greeks = asRecord(row.greeks_monitoring ?? row.greeks);
                    const status = fmt(row.status ?? risk.status ?? "research_only");
                    return (
                      <tr key={index}>
                        <td className="font-black">{fmt(row.strategy_type)}</td>
                        <td><Badge>{status}</Badge></td>
                        <td>{fmtPrice(row.bid ?? row.net_debit)} / {fmtPrice(row.ask ?? row.net_credit)}</td>
                        <td>{fmt(iv.iv_rank ?? row.iv_rank)}</td>
                        <td>{fmt(greeks.greeks_quality ?? row.greeks_quality)}</td>
                        <td>{fmt(row.days_to_expiration ?? risk.days_to_expiration)}</td>
                        <td>{fmt(row.reason ?? risk.reason ?? risk.block_reason ?? row.selection_reason)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <div className="mt-6"><JsonPanel data={result} /></div>
        </>
      ) : null}
    </div>
  );
}
