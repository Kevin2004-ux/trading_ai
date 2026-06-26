"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiGet, asList } from "@/lib/api";
import { fmt, fmtPrice } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";

function isClosed(row: Record<string, unknown>): boolean {
  const text = `${row.status ?? ""} ${row.recommendation_status ?? ""} ${row.outcome ?? ""}`.toLowerCase();
  return ["closed", "win", "loss", "expired"].some((token) => text.includes(token));
}

function TradeCard({ row }: { row: Record<string, unknown> }) {
  return (
    <article className="rounded-[1.6rem] border border-white/70 bg-white/80 p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-stone-500">Paper trade #{fmt(row.id)}</div>
          <h3 className="mt-1 text-3xl font-black text-ink">
            <Link className="text-tide underline-offset-4 hover:underline focus:outline-none focus:ring-2 focus:ring-tide" href={`/trades/${row.id}`}>
              {fmt(row.ticker)}
            </Link>
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge>{fmt(row.status ?? row.recommendation_status)}</Badge>
            <Badge tone="neutral">{fmt(row.asset_type, "asset")}</Badge>
            <Badge tone="neutral">Paper only</Badge>
          </div>
        </div>
        <div className="text-right text-sm">
          <div className="font-bold text-stone-500">Outcome</div>
          <div className="text-xl font-black text-ink">{fmt(row.outcome ?? row.latest_outcome, "Open")}</div>
        </div>
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Entry</dt><dd>{fmtPrice(row.entry_price)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Current / exit</dt><dd>{fmtPrice(row.current_price ?? row.exit_price)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Target</dt><dd>{fmtPrice(row.target_price)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Stop</dt><dd>{fmtPrice(row.stop_loss)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Risk/reward</dt><dd>{fmt(row.risk_reward)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Setup</dt><dd>{fmt(row.setup_type ?? row.strategy)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Direction</dt><dd>{fmt(row.direction)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Created</dt><dd>{fmt(row.created_at)}</dd></div>
      </dl>
      <p className="mt-4 text-sm leading-6 text-stone-700">{fmt(row.thesis ?? row.notes ?? row.invalidation, "No thesis note returned.")}</p>
    </article>
  );
}

export default function TradesPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    apiGet("/api/trades").then(setData);
  }, []);

  const rows = asList(data?.trades);
  const filtered = useMemo(() => {
    return rows
      .filter((row) => !search || String(row.ticker ?? "").toLowerCase().includes(search.toLowerCase()))
      .filter((row) => status === "all" || (status === "open" ? !isClosed(row) : isClosed(row)))
      .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
  }, [rows, search, status]);
  const openRows = filtered.filter((row) => !isClosed(row));
  const closedRows = filtered.filter(isClosed);

  return (
    <div>
      <PageHeader eyebrow="Paper trades" title="Simulated trade journal" description="SQLite-backed paper recommendations and outcomes. This is not a brokerage-position page." />
      <section className="mb-5 grid gap-3 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-3">
        <label className="text-sm font-bold">Search ticker
          <input className="mt-2 w-full rounded-xl border p-3 focus:outline-none focus:ring-2 focus:ring-tide" placeholder="AAPL" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label className="text-sm font-bold">View
          <select className="mt-2 w-full rounded-xl border p-3 focus:outline-none focus:ring-2 focus:ring-tide" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All paper records</option>
            <option value="open">Open paper trades</option>
            <option value="closed">Closed paper trades</option>
          </select>
        </label>
        <Card title="Safety" value={<Badge tone="neutral">Paper only</Badge>} detail="No buy, sell, or order actions are available." />
      </section>

      {!rows.length ? (
        <section className="rounded-[2rem] border border-dashed border-stone-300 bg-white/55 p-8 text-center">
          <Badge tone="neutral">No paper trades</Badge>
          <p className="mt-3 text-sm text-stone-600">No simulated recommendations are logged yet. Run a scan or ask chat for ideas; logging still requires backend guardrails.</p>
        </section>
      ) : null}

      <section className="mt-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-black">Open paper trades</h2>
          <Badge tone={openRows.length ? "research" : "neutral"}>{openRows.length}</Badge>
        </div>
        {openRows.length ? <div className="space-y-4">{openRows.map((row) => <TradeCard key={String(row.id)} row={row} />)}</div> : <p className="rounded-2xl bg-white/60 p-4 text-sm text-stone-600">No open paper trades match this filter.</p>}
      </section>

      <section className="mt-8 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-black">Closed paper trades</h2>
          <Badge tone={closedRows.length ? "research" : "neutral"}>{closedRows.length}</Badge>
        </div>
        {closedRows.length ? <div className="space-y-4">{closedRows.map((row) => <TradeCard key={String(row.id)} row={row} />)}</div> : <p className="rounded-2xl bg-white/60 p-4 text-sm text-stone-600">No closed paper trades match this filter.</p>}
      </section>

      <div className="mt-6">
        <JsonPanel title="Advanced trade JSON" data={data} />
      </div>
    </div>
  );
}
