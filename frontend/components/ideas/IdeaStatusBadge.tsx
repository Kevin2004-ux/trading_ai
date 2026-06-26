import { Badge } from "@/components/Badge";

export function IdeaStatusBadge({ status, assetType }: { status?: string | null; assetType?: string | null }) {
  const normalized = String(status || "unknown").toLowerCase();
  let label = String(status || "unknown").replaceAll("_", " ");
  let tone: "good" | "warning" | "blocked" | "research" | "neutral" = "neutral";
  if (normalized.includes("paper_eligible") || normalized.includes("recommendable")) {
    label = "Paper eligible";
    tone = "good";
  } else if (normalized.includes("research_only")) {
    label = "Research only";
    tone = "research";
  } else if (normalized.includes("watch")) {
    label = assetType === "option_underlying" ? "Underlying watchlist" : "Watchlist only";
    tone = "warning";
  } else if (normalized.includes("block") || normalized.includes("reject") || normalized.includes("fail")) {
    label = "Blocked";
    tone = "blocked";
  }
  return <Badge tone={tone}>{label}</Badge>;
}
