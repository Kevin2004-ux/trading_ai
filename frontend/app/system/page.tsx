"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL, apiGet, apiPost, asRecord, pickNested } from "@/lib/api";
import { fmt } from "@/lib/format";
import { learningSummary } from "@/lib/tradingTypes";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

function statusBadge(value: unknown) {
  return <Badge>{fmt(value, "unknown")}</Badge>;
}

export default function SystemPage() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [debug, setDebug] = useState<Record<string, unknown> | null>(null);
  const [learning, setLearning] = useState<Record<string, unknown> | null>(null);
  const [active, setActive] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState("");

  async function refresh() {
    const [statusResult, readinessResult, debugResult, learningResult] = await Promise.all([
      apiGet("/api/status"),
      apiGet("/api/readiness"),
      apiGet("/api/frontend-debug"),
      apiGet("/api/learning/status")
    ]);
    setStatus(statusResult);
    setReadiness(readinessResult);
    setDebug(debugResult);
    setLearning(learningResult);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function run(label: string, fn: () => Promise<Record<string, unknown>>) {
    setLoading(label);
    setActive(await fn());
    setLoading("");
  }

  const categories = asRecord(readiness?.categories);
  const learningStatus = learningSummary(learning ?? status?.learning);
  const warnings = useMemo(() => {
    return [
      ...(Array.isArray(status?.warnings) ? (status?.warnings as string[]) : []),
      ...(Array.isArray(readiness?.warnings) ? (readiness?.warnings as string[]) : []),
      ...(Array.isArray(debug?.known_warnings) ? (debug?.known_warnings as string[]) : []),
      ...(Array.isArray(learning?.warnings) ? (learning?.warnings as string[]) : [])
    ].filter(Boolean);
  }, [status, readiness, debug, learning]);

  return (
    <div>
      <PageHeader
        eyebrow="System"
        title="Runtime health and readiness"
        description="Grouped diagnostics for backend health, provider readiness, AI planning, options permissions, paper safety, and learning state."
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title="Backend" value={<Badge tone={status?.ok ? "good" : "blocked"}>{fmt(status?.backend, "unreachable")}</Badge>} detail={API_BASE_URL} />
        <Card title="Database" value={<Badge tone={status?.database_ready ? "good" : "blocked"}>{status?.database_ready ? "ready" : "check db"}</Badge>} detail="SQLite source of truth for trades, outcomes, policies, and learning snapshots." />
        <Card title="Paper safety" value={<Badge tone={status?.brokerage_execution_enabled ? "blocked" : "good"}>{status?.brokerage_execution_enabled ? "execution enabled" : "execution disabled"}</Badge>} detail="No order placement is exposed by this UI." />
        <Card title="Frontend bridge" value={statusBadge(status?.frontend_bridge ?? debug?.frontend_bridge)} detail="FastAPI calls stay behind typed UI helpers." />
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card title="Market data / IBKR">
          <dl className="space-y-2 text-sm">
            <div><dt className="font-bold">IBKR configured</dt><dd>{status?.ibkr_configured ? "Yes" : "No or incomplete"}</dd></div>
            <div><dt className="font-bold">Readiness</dt><dd>{fmt(readiness?.readiness ?? pickNested(status, "readiness.readiness"))}</dd></div>
            <div><dt className="font-bold">Remediation</dt><dd>Start and log into TWS. Enable API socket access. Confirm localhost port 7496.</dd></div>
          </dl>
        </Card>
        <Card title="Options readiness">
          <dl className="space-y-2 text-sm">
            <div><dt className="font-bold">Status</dt><dd>{fmt(asRecord(categories.options_ready).status ?? pickNested(status, "readiness.categories.options_ready.status"))}</dd></div>
            <div><dt className="font-bold">OPRA / quotes</dt><dd>Option quotes require the appropriate permissions; metadata alone is not enough for exact contracts.</dd></div>
            <div><dt className="font-bold">Final option trades</dt><dd>Blocked unless bid/ask, IV, Greeks, spread, liquidity, and fill quality pass backend gates.</dd></div>
          </dl>
        </Card>
        <Card title="AI planning and research">
          <dl className="space-y-2 text-sm">
            <div><dt className="font-bold">Planner</dt><dd>{fmt(status?.ai_planner_provider, status?.gemini_available ? "Gemini/OpenAI available" : "deterministic fallback")}</dd></div>
            <div><dt className="font-bold">Current research</dt><dd>{fmt(status?.ai_research_provider, "local/unavailable")}</dd></div>
            <div><dt className="font-bold">Gemini</dt><dd>{fmt(status?.gemini_status, "unknown")}</dd></div>
            <div><dt className="font-bold">Remediation</dt><dd>Configure OPENAI_API_KEY for AI planning/research when desired.</dd></div>
          </dl>
        </Card>
      </section>

      <section className="mt-6 rounded-[2rem] border border-white/70 bg-white/75 p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.22em] text-moss">Learning</div>
            <h2 className="mt-1 text-2xl font-black">Research-policy learning status</h2>
            <p className="mt-1 text-sm text-stone-600">Read-only status. Promotion remains manual and governed by backend policy controls.</p>
          </div>
          <Badge tone={learningStatus.status === "ready" ? "good" : learningStatus.status === "degraded" ? "blocked" : "research"}>
            {fmt(learningStatus.status, "collecting data")}
          </Badge>
        </div>
        <dl className="mt-4 grid gap-3 text-sm md:grid-cols-3">
          <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Active policy</dt><dd className="break-all">{fmt(learningStatus.active_policy_version)}</dd></div>
          <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Candidate snapshots</dt><dd>{fmt(learningStatus.candidate_snapshot_count)}</dd></div>
          <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Mature outcomes</dt><dd>{fmt(learningStatus.mature_outcome_count)}</dd></div>
          <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Pending outcomes</dt><dd>{fmt(learningStatus.pending_outcome_count)}</dd></div>
          <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Walk-forward ready</dt><dd>{fmt(learningStatus.walk_forward_ready, "No")}</dd></div>
          <div className="rounded-2xl bg-stone-50 p-3"><dt className="font-bold">Promotion ready</dt><dd>{fmt(learningStatus.promotion_ready, "No")}</dd></div>
        </dl>
      </section>

      <section className="mt-6 grid gap-3 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-3 xl:grid-cols-6">
        <button className="rounded-xl bg-ink p-3 font-bold text-white focus:outline-none focus:ring-2 focus:ring-tide" onClick={() => run("backend", () => apiGet("/api/status"))} type="button">Test backend</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white focus:outline-none focus:ring-2 focus:ring-tide" onClick={() => run("config", () => apiPost("/api/system/config-check", {}))} type="button">Config check</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white focus:outline-none focus:ring-2 focus:ring-tide" onClick={() => run("readiness", () => apiPost("/api/system/readiness-check", {}))} type="button">Readiness</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white focus:outline-none focus:ring-2 focus:ring-tide" onClick={() => run("db", () => apiGet("/api/db-status"))} type="button">DB status</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white focus:outline-none focus:ring-2 focus:ring-tide" onClick={() => run("dry", () => apiPost("/api/system/live-dry-run", { ticker: "AAPL", include_options: false, include_news: false, include_sec_filings: false, include_earnings_transcripts: false }))} type="button">Stock dry run</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white focus:outline-none focus:ring-2 focus:ring-tide" onClick={() => run("options", () => apiPost("/api/options/strategies", { ticker: "AAPL" }))} type="button">Options check</button>
      </section>

      {loading ? <p className="mt-4 text-sm font-bold" aria-live="polite">Running {loading}...</p> : null}
      <div className="mt-6"><WarningBox title="System warnings and remediation" items={[...new Set(warnings)].slice(0, 12)} /></div>

      <section className="mt-6 rounded-3xl border border-stone-200 bg-white/50 p-4">
        <h2 className="mb-3 text-lg font-black">Advanced diagnostics</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <JsonPanel title="Last action result" data={active} />
          <JsonPanel title="Backend status" data={status} />
          <JsonPanel title="Readiness payload" data={readiness} />
          <JsonPanel title="Learning payload" data={learning} />
          <JsonPanel title="Frontend debug" data={debug} />
        </div>
      </section>
    </div>
  );
}
