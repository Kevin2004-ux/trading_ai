import { ResearchSource, safeHttpUrl } from "@/lib/tradingTypes";

export function ResearchSources({
  sources,
  sourceIds,
  compact = true
}: {
  sources: ResearchSource[];
  sourceIds?: Array<string | number>;
  compact?: boolean;
}) {
  const allowed = sources.filter((source) => safeHttpUrl(source.url));
  const filtered = sourceIds?.length
    ? allowed.filter((source) => source.sourceId !== undefined && sourceIds.map(String).includes(String(source.sourceId)))
    : allowed;
  const rows = filtered.slice(0, compact ? 5 : 12);
  if (!rows.length) return null;
  return (
    <details className="mt-3 rounded-2xl border border-stone-200 bg-white/65 p-3">
      <summary className="cursor-pointer text-sm font-black text-ink focus:outline-none focus:ring-2 focus:ring-tide">
        Research sources ({rows.length})
      </summary>
      <div className="mt-3 space-y-2 text-sm">
        {rows.map((source, index) => (
          <a
            key={`${source.url}-${index}`}
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-xl bg-stone-50 p-3 text-tide underline-offset-4 hover:underline focus:outline-none focus:ring-2 focus:ring-tide"
          >
            [{source.sourceId ?? index + 1}] {source.title}
            {source.domain ? <span className="text-stone-500"> ({source.domain})</span> : null}
          </a>
        ))}
      </div>
    </details>
  );
}
