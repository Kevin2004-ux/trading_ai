import { Badge } from "@/components/Badge";
import { fmt } from "@/lib/format";
import { RefinementSummary as RefinementSummaryType, ScanSummary } from "@/lib/tradingTypes";

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="text-xs font-black uppercase tracking-[0.18em] text-moss">{title}</div>
      <ul className="mt-2 space-y-1 text-sm leading-6 text-stone-700">
        {items.slice(0, 6).map((item) => (
          <li key={item}>- {item}</li>
        ))}
      </ul>
    </div>
  );
}

export function RefinementSummary({
  refinement,
  scanSummary
}: {
  refinement: RefinementSummaryType;
  scanSummary: ScanSummary;
}) {
  return (
    <section className="rounded-3xl border border-white/70 bg-white/75 p-5 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.22em] text-moss">Scan and refinement</div>
          <h3 className="mt-1 text-2xl font-black">Adaptive execution summary</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={refinement.used ? "research" : "neutral"}>{refinement.used ? "Adaptive scan" : "Single pass"}</Badge>
          <Badge tone="neutral">{fmt(refinement.passes_executed, "1")} pass(es)</Badge>
          <Badge tone={scanSummary.include_options ? "research" : "neutral"}>{scanSummary.include_options ? "Options included" : "Stock only"}</Badge>
        </div>
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Universe</dt><dd>{fmt(scanSummary.universe)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Tickers scanned</dt><dd>{fmt(scanSummary.tickers_scanned)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Run ID</dt><dd className="break-all">{fmt(scanSummary.run_id)}</dd></div>
        <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Stop reason</dt><dd>{fmt(refinement.stop_reason, "No refinement note")}</dd></div>
      </dl>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <List title="Refinement changes" items={refinement.changes || []} />
        <List title="Refinement warnings" items={refinement.warnings || []} />
      </div>
    </section>
  );
}
