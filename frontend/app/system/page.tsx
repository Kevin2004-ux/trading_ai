"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL, apiGet, apiPost, asRecord } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

export default function SystemPage() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [debug, setDebug] = useState<Record<string, unknown> | null>(null);
  const [active, setActive] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState("");

  async function refresh() {
    const [statusResult, readinessResult, debugResult] = await Promise.all([
      apiGet("/api/status"),
      apiGet("/api/readiness"),
      apiGet("/api/frontend-debug")
    ]);
    setStatus(statusResult);
    setReadiness(readinessResult);
    setDebug(debugResult);
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
  const warnings = [
    ...(Array.isArray(status?.warnings) ? (status?.warnings as string[]) : []),
    ...(Array.isArray(readiness?.warnings) ? (readiness?.warnings as string[]) : []),
    ...(Array.isArray(debug?.known_warnings) ? (debug?.known_warnings as string[]) : [])
  ];

  return (
    <div>
      <PageHeader
        eyebrow="System"
        title="Frontend bridge control center"
        description="Check backend status, API bridge health, Gemini fallback, SQLite readiness, and read-only provider diagnostics from one operator page."
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title="Backend" value={<Badge tone={status?.ok ? "good" : "blocked"}>{fmt(status?.backend, "unreachable")}</Badge>} detail={API_BASE_URL} />
        <Card title="API bridge" value={<Badge>{fmt(status?.frontend_bridge ?? debug?.frontend_bridge, "unknown")}</Badge>} detail="Sync engine calls run outside FastAPI's event loop." />
        <Card title="Gemini" value={<Badge tone={status?.gemini_available ? "good" : "research"}>{status?.gemini_available ? "available" : "fallback"}</Badge>} detail={fmt(status?.gemini_status ?? debug?.gemini_status)} />
        <Card title="SQLite" value={<Badge tone={status?.database_ready ? "good" : "blocked"}>{status?.database_ready ? "ready" : "check db"}</Badge>} detail="Structured source of truth." />
      </section>

      <section className="mt-6 grid gap-3 rounded-3xl bg-white/75 p-5 shadow-card md:grid-cols-3 xl:grid-cols-6">
        <button className="rounded-xl bg-ink p-3 font-bold text-white" onClick={() => run("backend", () => apiGet("/api/status"))} type="button">Test backend</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white" onClick={() => run("config", () => apiPost("/api/system/config-check", {}))} type="button">Run config check</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white" onClick={() => run("readiness", () => apiPost("/api/system/readiness-check", {}))} type="button">Run readiness</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white" onClick={() => run("db", () => apiGet("/api/db-status"))} type="button">Run DB status</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white" onClick={() => run("dry", () => apiPost("/api/system/live-dry-run", { ticker: "AAPL", include_options: false, include_news: false, include_sec_filings: false, include_earnings_transcripts: false }))} type="button">Live dry run AAPL</button>
        <button className="rounded-xl bg-ink p-3 font-bold text-white" onClick={() => run("options", () => apiPost("/api/options/strategies", { ticker: "AAPL" }))} type="button">Options AAPL</button>
      </section>

      {loading ? <p className="mt-4 text-sm font-bold">Running {loading}...</p> : null}
      <div className="mt-6"><WarningBox title="System warnings" items={[...new Set(warnings)].slice(0, 12)} /></div>

      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <Card title="IBKR/TWS" detail={status?.ibkr_configured ? "IBKR environment variables detected. Run live dry run to verify TWS connectivity." : "IBKR environment variables are not fully configured."}>
          <Badge tone={status?.ibkr_configured ? "research" : "neutral"}>{status?.ibkr_configured ? "configured" : "not configured"}</Badge>
        </Card>
        <Card title="Options quote status" detail={fmt(asRecord(categories.options_ready).message, "Run Options AAPL to check option-chain availability.")}>
          <Badge>{fmt(asRecord(categories.options_ready).status, "unknown")}</Badge>
        </Card>
        <Card title="Paper-only safety" detail="No buy, sell, order, brokerage, or execution routes are exposed.">
          <Badge tone={status?.brokerage_execution_enabled ? "blocked" : "good"}>
            {status?.brokerage_execution_enabled ? "execution enabled" : "execution disabled"}
          </Badge>
        </Card>
        <Card title="Frontend API base" detail={API_BASE_URL}>
          <Badge tone={status?.ok ? "good" : "blocked"}>{status?.ok ? "connected" : "unreachable"}</Badge>
        </Card>
      </section>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <JsonPanel title="Last action result" data={active} />
        <JsonPanel title="Backend status" data={status} />
        <JsonPanel title="Frontend debug" data={debug} />
        <JsonPanel title="Readiness payload" data={readiness} />
      </div>
    </div>
  );
}
