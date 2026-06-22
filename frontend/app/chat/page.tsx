"use client";

import { useState } from "react";
import { apiPost, asList, asRecord } from "@/lib/api";
import { Badge } from "@/components/Badge";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

const examples = [
  "Find the best stock setups this week",
  "Find the best option setups this week",
  "Review AAPL",
  "Explain why no trades were selected",
  "Show research-only option ideas"
];

export default function ChatPage() {
  const [message, setMessage] = useState(examples[0]);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit() {
    setLoading(true);
    const response = await apiPost("/api/chat", { message });
    setResult(response);
    setLoading(false);
  }

  const validation = asRecord(result?.validation);
  const bestIdeas = asRecord(result?.best_available_ideas);
  const paperEligible = asList(bestIdeas.paper_eligible);
  const stockWatchlist = asList(bestIdeas.stock_watchlist);
  const optionResearch = asList(bestIdeas.option_research_only);
  const blockedInteresting = asList(bestIdeas.blocked_but_interesting);
  const warnings = Array.isArray(result?.warnings) ? (result?.warnings as string[]) : [];
  const systemIssues = Array.isArray(bestIdeas.system_issues) ? (bestIdeas.system_issues as string[]) : [];

  return (
    <div>
      <PageHeader eyebrow="Gemini assistant" title="Ask, but verify" description="The assistant can explain backend outputs. Deterministic tools and validation remain the source of truth." />
      <WarningBox items={["Gemini cannot override failed constraints.", "If validation fails or Gemini is unavailable, show deterministic fallback output."]} />
      <section className="mt-6 rounded-3xl bg-white/75 p-5 shadow-card">
        <div className="flex flex-wrap gap-2">
          {examples.map((item) => (
            <button key={item} className="rounded-full bg-stone-100 px-3 py-2 text-xs font-bold hover:bg-amberline" onClick={() => setMessage(item)} type="button">
              {item}
            </button>
          ))}
        </div>
        <textarea className="mt-4 min-h-32 w-full rounded-2xl border border-stone-200 bg-white p-4 text-sm outline-none focus:border-tide" value={message} onChange={(event) => setMessage(event.target.value)} />
        <button className="mt-3 rounded-2xl bg-ink px-5 py-3 font-bold text-white disabled:opacity-50" onClick={submit} disabled={loading} type="button">
          {loading ? "Asking..." : "Send to backend"}
        </button>
      </section>
      {result ? (
        <section className="mt-6 space-y-4 rounded-3xl bg-white/75 p-5 shadow-card">
          <div className="flex flex-wrap gap-2">
            <Badge>{String(validation.validation_status ?? "unknown")}</Badge>
            <Badge>{String(result.mode ?? "backend")}</Badge>
            <Badge tone={result.gemini_available ? "good" : "research"}>
              {result.gemini_available ? "Gemini available" : "Deterministic fallback"}
            </Badge>
            <Badge tone="neutral">Paper trading only</Badge>
          </div>
          <div className="whitespace-pre-wrap rounded-2xl bg-stone-50 p-4 text-sm leading-7">{String(result.answer ?? result.error ?? "No answer returned.")}</div>
          {paperEligible.length || stockWatchlist.length || optionResearch.length || blockedInteresting.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              <IdeaMiniBucket title="Paper eligible" rows={paperEligible} />
              <IdeaMiniBucket title="Stock watchlist" rows={stockWatchlist} />
              <IdeaMiniBucket title="Option research-only" rows={optionResearch} />
              <IdeaMiniBucket title="Blocked but interesting" rows={blockedInteresting} />
            </div>
          ) : null}
          <WarningBox title="Warnings" items={warnings} />
          <WarningBox title="System issues" items={systemIssues} />
          <JsonPanel data={result} />
        </section>
      ) : null}
    </div>
  );
}

function IdeaMiniBucket({ title, rows }: { title: string; rows: Record<string, unknown>[] }) {
  return (
    <div className="rounded-2xl border border-stone-200 bg-white/70 p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-black">{title}</h3>
        <Badge tone={rows.length ? "research" : "neutral"}>{rows.length}</Badge>
      </div>
      {rows.length ? (
        <div className="mt-3 space-y-2">
          {rows.slice(0, 5).map((row, index) => (
            <div key={`${row.idea_key ?? row.ticker}-${index}`} className="rounded-xl bg-stone-50 p-3 text-sm">
              <div className="font-black">{String(row.ticker ?? row.option_contract ?? "Unknown")}</div>
              <div className="text-stone-600">{String(row.reason ?? row.rejection_reason ?? "No reason provided.")}</div>
            </div>
          ))}
        </div>
      ) : <p className="mt-3 text-sm text-stone-600">No rows in this bucket.</p>}
    </div>
  );
}
