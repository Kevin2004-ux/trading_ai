"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, asRecord, pickNested } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

const links = [
  ["/chat", "Ask the assistant", "Gemini/tooling with deterministic fallback"],
  ["/scan", "Run scan", "Paper-cycle controls and candidate review"],
  ["/trades", "Trade library", "SQLite paper recommendations and outcomes"],
  ["/performance", "Performance", "Win rate, expectancy, diagnostics"],
  ["/options", "Options research", "Research-only option strategy gating"],
  ["/system", "System readiness", "Config, DB, live dry run, stress"],
  ["/reports", "Reports", "Alerts, jobs, stress suite, reports"]
];

export default function DashboardHome() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiGet("/api/status").then(setStatus);
  }, []);

  const readiness = asRecord(status?.readiness);
  const paper = asRecord(status?.paper_summary);
  const paperSummary = asRecord(paper.summary);
  const alerts = asRecord(status?.alerts);
  const warnings = Array.isArray(status?.warnings) ? (status?.warnings as string[]) : [];

  return (
    <div>
      <PageHeader
        eyebrow="Dashboard home"
        title="Paper-trading cockpit"
        description="A frontend view over the deterministic FastAPI backend. No trading logic lives here, and no real brokerage orders are available."
      />

      <WarningBox
        items={[
          "Paper trading and simulation only.",
          "Gemini, memory, and frontend displays cannot override deterministic backend gates.",
          "Options stay blocked unless backend quote, IV, Greeks, DTE, spread, fill, and strategy gates pass."
        ]}
      />

      <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title="Readiness" value={fmt(readiness.readiness, "Loading")} detail={<Badge>{fmt(readiness.readiness, "unknown")}</Badge>} />
        <Card title="Selected count" value={fmt(paperSummary.selected_count ?? pickNested(paper, "summary.selected_count"), "0")} detail="Latest paper-cycle selection count" />
        <Card title="Logged count" value={fmt(paperSummary.logged_count ?? pickNested(paper, "summary.logged_count"), "0")} detail="Latest paper records logged" />
        <Card title="Alerts" value={fmt(alerts.count, "0")} detail={`Severity: ${fmt(JSON.stringify(alerts.severity_counts ?? {}))}`} />
      </section>

      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <Card title="Options status" detail="Frontend only displays backend option gating output.">
          <Badge tone="research">{fmt(pickNested(readiness, "categories.options_ready.status"), "research-only / blocked")}</Badge>
        </Card>
        <Card title="Backend URL" detail={process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}>
          <Badge tone={status?.ok ? "good" : "blocked"}>{status?.ok ? "Connected" : "Loading or unavailable"}</Badge>
        </Card>
      </section>

      <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {links.map(([href, title, description]) => (
          <Link key={href} href={href} className="group rounded-3xl border border-white/70 bg-white/75 p-5 shadow-card transition hover:-translate-y-1 hover:bg-ink hover:text-white">
            <div className="text-lg font-black">{title}</div>
            <p className="mt-2 text-sm text-stone-600 group-hover:text-stone-200">{description}</p>
          </Link>
        ))}
      </section>

      {warnings.length ? <div className="mt-6"><WarningBox title="Current backend warnings" items={warnings.slice(0, 8)} /></div> : null}
      <div className="mt-6">
        <JsonPanel data={status} />
      </div>
    </div>
  );
}
