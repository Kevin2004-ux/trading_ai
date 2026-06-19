"use client";

import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, pickNested } from "@/lib/api";
import { fmt, fmtPercent } from "@/lib/format";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";

export default function PerformancePage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiGet("/api/performance").then(setData);
  }, []);

  const winLoss = asRecord(data?.win_loss_record);
  const diagnostics = asRecord(data?.diagnostics);
  const sections = asList(diagnostics.sections);
  const perfData = asRecord(sections.find((section) => String(section.title).includes("Performance Attribution"))?.data);
  const setupRows = asList(pickNested(data, "strategy_performance.by_setup_type"));

  return (
    <div>
      <PageHeader eyebrow="Performance" title="Paper-trading feedback loop" description="Performance, attribution, setup diagnostics, and error analysis from SQLite paper records." />
      <section className="grid gap-4 md:grid-cols-4">
        <Card title="Win rate" value={fmtPercent(winLoss.win_rate)} />
        <Card title="Expectancy R" value={fmt(perfData.expectancy_r ?? winLoss.expectancy)} />
        <Card title="Profit factor" value={fmt(perfData.profit_factor)} />
        <Card title="Max drawdown R" value={fmt(perfData.max_drawdown_r)} />
        <Card title="Closed trades" value={fmt(winLoss.closed_trades ?? perfData.closed_trade_count)} />
        <Card title="Open trades" value={fmt(winLoss.open ?? perfData.open_trade_count)} />
        <Card title="Average win R" value={fmt(perfData.average_win_r ?? winLoss.avg_win_return)} />
        <Card title="Average loss R" value={fmt(perfData.average_loss_r ?? winLoss.avg_loss_return)} />
      </section>
      <section className="mt-6 rounded-3xl bg-white/75 p-5 shadow-card">
        <h2 className="mb-3 text-2xl font-black">Setup diagnostics</h2>
        <div className="table-shell">
          <table className="data-table">
            <thead><tr><th>Setup</th><th>Total</th><th>Avg return</th><th>Win rate</th><th>Status</th></tr></thead>
            <tbody>
              {setupRows.map((row, index) => (
                <tr key={index}>
                  <td>{fmt(row.setup_type)}</td>
                  <td>{fmt(row.total_recommendations ?? row.sample_size)}</td>
                  <td>{fmt(row.average_realized_return ?? row.expectancy_r)}</td>
                  <td>{fmtPercent(row.win_rate)}</td>
                  <td>{fmt(row.status ?? row.diagnostic_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        {sections.map((section) => (
          <Card key={String(section.title)} title={String(section.title)} detail={String(section.body ?? "").slice(0, 420)} />
        ))}
      </section>
      <div className="mt-6"><JsonPanel data={data} /></div>
    </div>
  );
}
