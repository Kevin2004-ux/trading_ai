"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiGet, apiPost, asRecord } from "@/lib/api";
import { fmt, fmtPrice } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

export default function TradeDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [annotation, setAnnotation] = useState({ rating: 0, label: "", notes: "" });
  const [saved, setSaved] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiGet(`/api/trades/${params.id}`).then(setData);
  }, [params.id]);

  const trade = asRecord(data?.trade);

  async function saveAnnotation() {
    const response = await apiPost("/api/annotations", {
      entity_type: "trade",
      entity_id: String(params.id),
      ticker: trade.ticker,
      setup_type: trade.setup_type,
      annotation_type: "trade_note",
      rating: annotation.rating,
      label: annotation.label,
      notes: annotation.notes,
      payload: { source: "frontend" }
    });
    setSaved(response);
  }

  return (
    <div>
      <PageHeader eyebrow="Trade detail" title={`${fmt(trade.ticker, "Paper trade")} #${params.id}`} description="Full SQLite paper recommendation detail. Annotations are human notes only and do not override deterministic gates." />
      {!data?.ok ? <WarningBox title="Load status" items={[String(data?.error ?? "Loading trade detail...")]} /> : null}
      <section className="grid gap-4 md:grid-cols-4">
        <Card title="Setup" value={fmt(trade.setup_type)} detail={<Badge>{fmt(trade.status ?? trade.recommendation_status)}</Badge>} />
        <Card title="Entry / fill" value={fmtPrice(trade.entry_price)} detail={`Estimated fill: ${fmtPrice(trade.estimated_fill_price ?? trade.entry_price)}`} />
        <Card title="Target" value={fmtPrice(trade.target_price)} detail={`Stop: ${fmtPrice(trade.stop_loss)}`} />
        <Card title="R / outcome" value={fmt(trade.realized_return ?? trade.risk_reward)} detail={fmt(trade.outcome ?? trade.latest_outcome)} />
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card title="Why selected / logged reason">
          <p className="text-sm leading-7 text-stone-700">{fmt(trade.thesis ?? trade.notes ?? trade.invalidation)}</p>
        </Card>
        <Card title="Risk and context">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <dt className="font-bold">Direction</dt><dd>{fmt(trade.direction)}</dd>
            <dt className="font-bold">Asset type</dt><dd>{fmt(trade.asset_type)}</dd>
            <dt className="font-bold">Risk/reward</dt><dd>{fmt(trade.risk_reward)}</dd>
            <dt className="font-bold">Max risk</dt><dd>{fmt(trade.max_risk ?? trade.max_drawdown)}</dd>
          </dl>
        </Card>
      </section>

      <section className="mt-6 rounded-3xl bg-white/75 p-5 shadow-card">
        <h2 className="text-2xl font-black">Human annotation</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <input className="rounded-xl border p-3" type="number" value={annotation.rating} onChange={(e) => setAnnotation({ ...annotation, rating: Number(e.target.value) })} />
          <input className="rounded-xl border p-3" placeholder="Label" value={annotation.label} onChange={(e) => setAnnotation({ ...annotation, label: e.target.value })} />
          <button className="rounded-xl bg-ink px-4 py-3 font-bold text-white" onClick={saveAnnotation} type="button">Save note</button>
        </div>
        <textarea className="mt-3 min-h-28 w-full rounded-xl border p-3" placeholder="Notes" value={annotation.notes} onChange={(e) => setAnnotation({ ...annotation, notes: e.target.value })} />
        {saved ? <div className="mt-3"><Badge>{saved.ok ? "Saved" : "Error"}</Badge></div> : null}
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <JsonPanel title="Data snapshot" data={trade.data_snapshot_json ?? trade.data_snapshot} />
        <JsonPanel title="Model outputs / constraints" data={{ model_outputs: trade.model_outputs_json, constraints: trade.constraint_results_json }} />
        <JsonPanel title="Research, macro, memory, technical context" data={trade} />
        <JsonPanel title="Reviews and annotations response" data={{ loaded: data, saved }} />
      </section>
    </div>
  );
}
