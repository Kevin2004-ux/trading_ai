import { Badge } from "@/components/Badge";
import { fmt, fmtPrice, fmtPercent } from "@/lib/format";
import { OptionIdeaRow, ResearchSource } from "@/lib/tradingTypes";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { ResearchSources } from "./ResearchSources";

function metric(value: unknown, formatter: (value: unknown) => string = fmt): string {
  return value === null || value === undefined || value === "" ? "Not available" : formatter(value);
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
        {items.slice(0, 5).map((item) => (
          <li key={item}>- {item}</li>
        ))}
      </ul>
    </div>
  );
}

export function OptionIdeaCard({ idea, sources = [] }: { idea: OptionIdeaRow; sources?: ResearchSource[] }) {
  const normalized = idea.status.toLowerCase();
  const researchOnly = normalized.includes("research");
  const blocked = normalized.includes("block") || normalized.includes("reject");
  return (
    <article className={`rounded-[1.6rem] border bg-white/80 p-5 shadow-card ${blocked ? "border-red-200" : researchOnly ? "border-sky-200" : "border-emerald-200"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.2em] text-stone-500">Exact option #{fmt(idea.rank)}</div>
          <h3 className="mt-1 text-2xl font-black text-ink">{idea.ticker}</h3>
          <p className="mt-1 break-all text-sm font-semibold text-stone-600">{idea.option_contract || "No exact contract symbol returned"}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <IdeaStatusBadge status={idea.status} assetType="option" />
            <Badge tone="research">{fmt(idea.strategy ?? idea.option_type, "option strategy")}</Badge>
            {idea.underlying_status ? <Badge tone="neutral">Underlying {idea.underlying_status}</Badge> : null}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-stone-500">Option score</div>
          <div className="text-3xl font-black text-tide">{fmt(idea.opportunity_score, "N/A")}</div>
          <div className="text-xs text-stone-500">Underlying {fmt(idea.underlying_opportunity_score, "N/A")}</div>
        </div>
      </div>

      {researchOnly || blocked ? (
        <div className={`mt-4 rounded-2xl border p-3 text-sm font-semibold ${blocked ? "border-red-200 bg-red-50 text-red-900" : "border-sky-200 bg-sky-50 text-sky-950"}`}>
          {blocked
            ? "Blocked: exact option requirements did not pass. This is not a recommendation."
            : "Research only: exact contract data is displayable, but backend gates did not mark it paper eligible."}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <MiniMetric label="Strike" value={metric(idea.strike, fmtPrice)} />
        <MiniMetric label="Expiration" value={metric(idea.expiration)} />
        <MiniMetric label="DTE" value={metric(idea.days_to_expiration)} />
        <MiniMetric label="Bid / ask / mid" value={`${metric(idea.bid, fmtPrice)} / ${metric(idea.ask, fmtPrice)} / ${metric(idea.mid, fmtPrice)}`} />
        <MiniMetric label="Spread" value={metric(idea.spread_percent, fmtPercent)} />
        <MiniMetric label="Breakeven" value={metric(idea.breakeven_price, fmtPrice)} />
        <MiniMetric label="Open interest" value={metric(idea.open_interest)} />
        <MiniMetric label="Volume" value={metric(idea.volume)} />
        <MiniMetric label="IV" value={metric(idea.implied_volatility, fmtPercent)} />
        <MiniMetric label="IV rank" value={metric(idea.iv_rank)} />
        <MiniMetric label="Delta" value={metric(idea.delta)} />
        <MiniMetric label="Engine" value={metric(idea.engine_score)} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <TextList title="Why it ranked" items={idea.why_ranked} />
        <TextList title="Key risks" items={idea.key_risks} />
        <TextList title="Missing requirements" items={idea.missing_requirements} />
        <TextList title="Current catalysts" items={idea.current_catalysts} />
        <TextList title="Current risks" items={idea.current_risks} />
      </div>
      <ResearchSources sources={sources} sourceIds={idea.research_source_ids} />
    </article>
  );
}
