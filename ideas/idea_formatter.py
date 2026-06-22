from __future__ import annotations

from typing import Any


def _rows(items: list[dict], label: str, limit: int = 5) -> list[str]:
    if not items:
        return [f"{label}: none."]
    lines = [f"{label}:"]
    for index, item in enumerate(items[:limit], start=1):
        ticker = item.get("ticker") or item.get("option_contract") or "Unknown"
        status = item.get("recommendation_status") or item.get("bucket") or "unknown"
        score = item.get("idea_score") or item.get("score")
        reason = item.get("reason") or item.get("rejection_reason") or "No reason provided."
        lines.append(f"{index}. {ticker} ({status}, score {score}): {reason}")
    return lines


def _bullets(title: str, values: Any) -> list[str]:
    rows = values if isinstance(values, list) else []
    if not rows:
        return [f"{title}: none."]
    return [f"{title}:"] + [f"- {value}" for value in rows]


def format_best_ideas_response(best_ideas: dict) -> str:
    if not isinstance(best_ideas, dict) or not best_ideas.get("ok"):
        return "I could not build best available ideas from the deterministic backend result."

    lines: list[str] = []
    if best_ideas.get("paper_eligible"):
        lines.append("Final paper trades passed strict gates. These remain simulated-only.")
    else:
        lines.append("No final paper trades passed strict gates today.")

    lines.append("")
    lines.extend(_rows(best_ideas.get("paper_eligible", []), "Paper-eligible ideas"))
    lines.append("")
    lines.extend(_rows(best_ideas.get("stock_watchlist", []), "Best stock ideas to watch"))
    lines.append("")
    lines.extend(_rows(best_ideas.get("option_research_only", []), "Best option research ideas"))
    lines.append("")
    lines.extend(_rows(best_ideas.get("blocked_but_interesting", []), "Blocked but interesting"))
    lines.append("")
    lines.extend(_bullets("Why no final trades", best_ideas.get("why_no_final_trades")))
    lines.append("")
    lines.extend(_bullets("Data missing / system issues", list(best_ideas.get("data_missing", [])) + list(best_ideas.get("system_issues", []))))
    lines.append("")
    lines.extend(_bullets("What to fix next", best_ideas.get("next_steps")))
    lines.append("")
    lines.append("Gemini cannot override these deterministic buckets, and blocked/research-only ideas are not trade recommendations.")
    return "\n".join(lines)
