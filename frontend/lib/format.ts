export function fmt(value: unknown, fallback = "N/A"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString() : fallback;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function fmtPrice(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? `$${num.toFixed(2)}` : "N/A";
}

export function fmtPercent(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? `${num.toFixed(2)}%` : "N/A";
}

export function statusTone(status: unknown): "good" | "warning" | "blocked" | "research" | "neutral" {
  const label = String(status ?? "").toLowerCase();
  if (["ok", "pass", "ready", "running", "success", "win", "open", "paper_eligible", "recommendable"].some((word) => label.includes(word))) return "good";
  if (["warn", "watch", "fallback", "partial", "research_only", "research"].some((word) => label.includes(word))) return "research";
  if (["block", "fail", "error", "loss", "unavailable", "rejected", "not_ready"].some((word) => label.includes(word))) return "blocked";
  if (["stale", "manual", "review", "expired"].some((word) => label.includes(word))) return "warning";
  return "neutral";
}
