"use client";

import { useEffect, useState } from "react";
import { apiGet, asList, asRecord } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { JsonPanel } from "@/components/JsonPanel";
import { PageHeader } from "@/components/PageHeader";
import { WarningBox } from "@/components/WarningBox";

export default function ReportsPage() {
  const [performance, setPerformance] = useState<Record<string, unknown> | null>(null);
  const [alerts, setAlerts] = useState<Record<string, unknown> | null>(null);
  const [jobs, setJobs] = useState<Record<string, unknown> | null>(null);
  const [stress, setStress] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiGet("/api/reports/performance?format=dict").then(setPerformance);
    apiGet("/api/alerts").then(setAlerts);
    apiGet("/api/jobs").then(setJobs);
    apiGet("/api/stress/suite").then(setStress);
  }, []);

  const alertRows = asList(alerts?.alerts);
  const jobRows = asList(asRecord(jobs?.job_history).job_runs);
  const sections = asList(performance?.sections);

  return (
    <div>
      <PageHeader eyebrow="Reports" title="Diagnostics, jobs, alerts, stress" description="Copyable JSON and report summaries from the deterministic backend." />
      <section className="grid gap-4 md:grid-cols-4">
        <Card title="Performance report" value={<Badge>{performance?.ok ? "Ready" : "Loading"}</Badge>} detail={fmt(performance?.summary)} />
        <Card title="Alerts" value={fmt(alerts?.count, "0")} detail={fmt(JSON.stringify(alerts?.severity_counts ?? {}))} />
        <Card title="Recent jobs" value={fmt(asRecord(jobs?.job_history).count, "0")} />
        <Card title="Stress suite" value={<Badge>{stress?.ok ? "Pass" : "Check"}</Badge>} detail={`${fmt(stress?.scenario_count, "0")} scenarios`} />
      </section>
      <div className="mt-6">
        <WarningBox title="Report safety" items={["Reports summarize backend outputs and do not create trades.", "Stress tests are simulations, not guarantees."]} />
      </div>
      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        {sections.slice(0, 9).map((section) => (
          <Card key={String(section.title)} title={String(section.title)} detail={String(section.body ?? "").slice(0, 360)} />
        ))}
      </section>
      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card title="Latest alerts">
          <ul className="space-y-2 text-sm">
            {alertRows.slice(0, 8).map((alert, index) => (
              <li key={index} className="rounded-xl bg-stone-50 p-3">
                <Badge>{fmt(alert.severity)}</Badge> <span className="font-bold">{fmt(alert.title ?? alert.alert_type)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Recent scheduled jobs">
          <ul className="space-y-2 text-sm">
            {jobRows.slice(0, 8).map((job, index) => (
              <li key={index} className="rounded-xl bg-stone-50 p-3">
                <Badge>{fmt(job.status)}</Badge> <span className="font-bold">{fmt(job.job_name)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </section>
      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <JsonPanel title="Performance report JSON" data={performance} />
        <JsonPanel title="Stress suite JSON" data={stress} />
        <JsonPanel title="Alerts JSON" data={alerts} />
        <JsonPanel title="Jobs JSON" data={jobs} />
      </section>
    </div>
  );
}
