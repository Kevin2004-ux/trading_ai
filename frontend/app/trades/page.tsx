"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiGet, asList } from "@/lib/api";
import { fmt, fmtPrice } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";

export default function TradesPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [assetType, setAssetType] = useState("all");
  const [sort, setSort] = useState("date");

  useEffect(() => {
    apiGet("/api/trades").then(setData);
  }, []);

  const rows = asList(data?.trades);
  const filtered = useMemo(() => {
    return rows
      .filter((row) => !search || String(row.ticker ?? "").toLowerCase().includes(search.toLowerCase()))
      .filter((row) => status === "all" || String(row.status ?? row.recommendation_status ?? "").toLowerCase().includes(status))
      .filter((row) => assetType === "all" || String(row.asset_type ?? "").toLowerCase() === assetType)
      .sort((a, b) => {
        if (sort === "r") return Number(b.realized_return ?? b.r_multiple ?? 0) - Number(a.realized_return ?? a.r_multiple ?? 0);
        if (sort === "status") return String(a.status ?? "").localeCompare(String(b.status ?? ""));
        return String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""));
      });
  }, [rows, search, status, assetType, sort]);

  return (
    <div>
      <PageHeader eyebrow="Paper library" title="Logged paper trades" description="SQLite-backed paper recommendation records. Search, filter, sort, and open details without placing orders." />
      <section className="mb-5 grid gap-3 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-4">
        <input className="rounded-xl border p-3" placeholder="Search ticker" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="rounded-xl border p-3" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All status</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="win">Win</option>
          <option value="loss">Loss</option>
        </select>
        <select className="rounded-xl border p-3" value={assetType} onChange={(e) => setAssetType(e.target.value)}>
          <option value="all">All assets</option>
          <option value="stock">Stock</option>
          <option value="option">Option</option>
        </select>
        <select className="rounded-xl border p-3" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="date">Sort date</option>
          <option value="r">Sort R / return</option>
          <option value="status">Sort status</option>
        </select>
      </section>
      <div className="table-shell">
        <table className="data-table">
          <thead><tr><th>Ticker</th><th>Asset</th><th>Setup</th><th>Direction</th><th>Open date</th><th>Entry / Fill</th><th>Target</th><th>Stop</th><th>Status</th><th>Win/loss</th><th>Reason</th></tr></thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={String(row.id)}>
                <td><Link className="font-black text-tide underline" href={`/trades/${row.id}`}>{fmt(row.ticker)}</Link></td>
                <td>{fmt(row.asset_type)}</td>
                <td>{fmt(row.setup_type)}</td>
                <td>{fmt(row.direction)}</td>
                <td>{fmt(row.created_at)}</td>
                <td>{fmtPrice(row.entry_price)} / {fmtPrice(row.estimated_fill_price ?? row.entry_price)}</td>
                <td>{fmtPrice(row.target_price)}</td>
                <td>{fmtPrice(row.stop_loss)}</td>
                <td><Badge>{fmt(row.status ?? row.recommendation_status)}</Badge></td>
                <td>{fmt(row.outcome ?? row.latest_outcome)}</td>
                <td>{fmt(row.thesis ?? row.notes ?? row.rejection_reason)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-6"><JsonPanel data={data} /></div>
    </div>
  );
}
