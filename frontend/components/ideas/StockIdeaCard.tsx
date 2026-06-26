import { Badge } from "@/components/Badge";
import { fmt, fmtPrice } from "@/lib/format";
import { ResearchSource, StockIdeaRow } from "@/lib/tradingTypes";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { ResearchSources } from "./ResearchSources";

function priceOrDash(value: unknown): string {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? fmtPrice(numeric) : "Not provided";
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-stone-50 p-3">
      <div className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-stone-500">{label}</div>
      <div className="mt-1 font-black text-ink">{value}</div>
    </div>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="text-xs font-black uppercase tracking-[0.18em] text-moss">{title}</div>
      <ul className="mt-2 space-y-1 text-sm leading-6 text-stone-700">
        {items.slice(0, 4).map((item) => (
          <li key={item}>- {item}</li>
        ))}
      </ul>
    </div>
  );
}

export function StockIdeaCard({ idea, sources = [] }: { idea: StockIdeaRow; sources?: ResearchSource[] }) {
  const blocked = ["blocked", "rejected", "failed"].some((token) => idea.status.toLowerCase().includes(token));
  const watchlist = idea.status.toLowerCase().includes("watch");
  return (
    <article className={`rounded-[1.6rem] border bg-white/80 p-5 shadow-card ${blocked ? "border-red-200" : watchlist ? "border-amber-200" : "border-emerald-200"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.2em] text-stone-500">Stock idea #{fmt(idea.rank)}</div>
          <h3 className="mt-1 text-3xl font-black text-ink">{idea.ticker}</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            <IdeaStatusBadge status={idea.status} assetType="stock" />
            <Badge tone="neutral">{fmt(idea.direction, "direction unknown")}</Badge>
            {idea.setup ? <Badge tone="research">{idea.setup}</Badge> : null}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-stone-500">Opportunity</div>
          <div className="text-3xl font-black text-tide">{fmt(idea.opportunity_score, "N/A")}</div>
          <div className="text-xs text-stone-500">Engine {fmt(idea.engine_score, "N/A")}</div>
        </div>
      </div>

      {blocked || watchlist ? (
        <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/80 p-3 text-sm font-semibold text-amber-950">
          {blocked ? "Blocked: backend constraints did not allow this as a paper trade." : "Watchlist only: monitor for confirmation before it can become paper eligible."}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MiniMetric label="Entry" value={priceOrDash(idea.entry_price)} />
        <MiniMetric label="Target" value={priceOrDash(idea.target_price)} />
        <MiniMetric label="Stop" value={priceOrDash(idea.stop_loss)} />
        <MiniMetric label="Risk/reward" value={fmt(idea.risk_reward, "N/A")} />
        <MiniMetric label="Data quality" value={fmt(idea.data_quality && typeof idea.data_quality === "object" ? JSON.stringify(idea.data_quality).slice(0, 44) : idea.data_quality, "unknown")} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <TextList title="Why it ranked" items={idea.why_ranked} />
        <TextList title="Risks" items={idea.key_risks} />
        <TextList title="Confirmation needed" items={idea.confirmation_needed} />
        <TextList title="Failed constraints" items={idea.failed_constraints} />
        <TextList title="Current catalysts" items={idea.current_catalysts} />
        <TextList title="Current risks" items={idea.current_risks} />
      </div>

      {idea.research_summary ? (
        <p className="mt-4 rounded-2xl bg-stone-50 p-3 text-sm leading-6 text-stone-700">
          <span className="font-black">Research:</span> {idea.research_summary}
        </p>
      ) : null}
      <ResearchSources sources={sources} sourceIds={idea.research_source_ids} />
    </article>
  );
}
