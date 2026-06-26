import { Badge } from "@/components/Badge";
import { fmt } from "@/lib/format";
import { OptionUnderlyingRow, ResearchSource } from "@/lib/tradingTypes";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { ResearchSources } from "./ResearchSources";

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

export function OptionUnderlyingCard({ idea, sources = [] }: { idea: OptionUnderlyingRow; sources?: ResearchSource[] }) {
  return (
    <article className="rounded-[1.6rem] border border-amber-200 bg-white/80 p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-[0.2em] text-stone-500">Option underlying #{fmt(idea.rank)}</div>
          <h3 className="mt-1 text-3xl font-black text-ink">{idea.ticker}</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            <IdeaStatusBadge status={idea.status} assetType="option_underlying" />
            <Badge tone="warning">Underlying watchlist - no exact contract ranked</Badge>
            {idea.option_bias ? <Badge tone="research">{idea.option_bias}</Badge> : null}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs font-bold uppercase tracking-[0.18em] text-stone-500">Underlying score</div>
          <div className="text-3xl font-black text-tide">{fmt(idea.underlying_opportunity_score, "N/A")}</div>
          <div className="text-xs text-stone-500">{fmt(idea.underlying_status, "status unknown")}</div>
        </div>
      </div>
      <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/80 p-3 text-sm font-semibold text-amber-950">
        Underlying watchlist - no exact contract ranked. Exact option research requires option chain, bid/ask, IV, Greeks, liquidity, and fill-quality data.
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <TextList title="Why monitor it" items={idea.why_watch} />
        <TextList title="Required before exact contract ranking" items={idea.required_before_contract_ranking} />
        <TextList title="Current catalysts" items={idea.current_catalysts} />
        <TextList title="Current risks" items={idea.current_risks} />
      </div>
      <ResearchSources sources={sources} sourceIds={idea.research_source_ids} />
    </article>
  );
}
