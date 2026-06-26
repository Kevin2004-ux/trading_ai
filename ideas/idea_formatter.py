from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _source_numbers(sources: list[dict]) -> dict[str, int]:
    return {str(source.get("source_id")): index for index, source in enumerate(sources, start=1) if source.get("source_id")}


def _source_refs(source_ids: list[Any], source_numbers: dict[str, int]) -> str:
    refs = [source_numbers[str(source_id)] for source_id in source_ids if str(source_id) in source_numbers]
    refs = list(dict.fromkeys(refs))[:2]
    return f" [{' '.join(f'[{ref}]' for ref in refs)}]" if refs else ""


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


def _assistant_rows(items: list[dict], label: str, limit: int = 5, source_numbers: dict[str, int] | None = None) -> list[str]:
    if not items:
        return [f"{label}: none."]
    source_numbers = source_numbers or {}
    lines = [f"{label}:"]
    for item in items[:limit]:
        name = item.get("ticker") or item.get("option_contract") or "Unknown"
        status = item.get("status") or "unknown"
        score = item.get("opportunity_score")
        why = item.get("why_ranked") if isinstance(item.get("why_ranked"), list) else []
        risks = item.get("key_risks") if isinstance(item.get("key_risks"), list) else []
        confirmations = item.get("confirmation_needed") if isinstance(item.get("confirmation_needed"), list) else []
        missing = item.get("missing_requirements") if isinstance(item.get("missing_requirements"), list) else []
        lines.append(f"{item.get('rank')}. {name} ({status}, opportunity score {score}): {why[0] if why else 'Ranked by deterministic criteria.'}")
        followups = risks[:1] + confirmations[:1] + missing[:1]
        if followups:
            lines.append(f"   Risk/confirmation: {followups[0]}")
        catalyst = _as_list(item.get("current_catalysts"))[:1]
        current_risk = _as_list(item.get("current_risks"))[:1]
        refs = _source_refs(_as_list(item.get("research_source_ids")), source_numbers)
        if catalyst:
            lines.append(f"   Current catalyst: {catalyst[0]}{refs}")
        if current_risk:
            lines.append(f"   Current risk: {current_risk[0]}{refs}")
    return lines


def _option_contract_rows(items: list[dict], label: str, status_filter: set[str] | None = None, limit: int = 5) -> list[str]:
    rows = [
        item for item in items
        if isinstance(item, dict) and (not status_filter or str(item.get("status") or "").lower() in status_filter)
    ]
    if not rows:
        return [f"{label}: none."]
    lines = [f"{label}:"]
    for item in rows[:limit]:
        contract = item.get("option_contract") or "Unknown contract"
        ticker = item.get("ticker") or "Unknown"
        strategy = item.get("strategy") or item.get("option_type") or "option"
        dte = item.get("days_to_expiration")
        expiration = item.get("expiration") or "unknown expiration"
        score = item.get("opportunity_score")
        bid = item.get("bid")
        ask = item.get("ask")
        mid = item.get("mid")
        spread = item.get("spread_percent")
        price_bits = []
        if bid is not None and ask is not None:
            price_bits.append(f"bid/ask {bid}/{ask}")
        elif mid is not None:
            price_bits.append(f"mid {mid}")
        if spread is not None:
            price_bits.append(f"spread {round(float(spread) * 100, 2)}%")
        price_text = "; ".join(price_bits) if price_bits else "quote unavailable"
        why = _as_list(item.get("why_ranked"))
        risks = _as_list(item.get("key_risks"))
        lines.append(f"{item.get('rank')}. {ticker} {contract} ({strategy}, {expiration}, DTE {dte}, score {score}): {price_text}.")
        if why:
            lines.append(f"   Why ranked: {why[0]}")
        if risks:
            lines.append(f"   Major risk: {risks[0]}")
    return lines


def _option_underlying_rows(items: list[dict], label: str, limit: int = 5) -> list[str]:
    if not items:
        return [f"{label}: none."]
    lines = [f"{label}:"]
    for item in items[:limit]:
        ticker = item.get("ticker") or "Unknown"
        bias = item.get("option_bias") or "unknown"
        score = item.get("underlying_opportunity_score")
        required = _as_list(item.get("required_before_contract_ranking"))
        why = _as_list(item.get("why_watch"))
        lines.append(f"{item.get('rank')}. {ticker} ({bias} options watchlist, underlying score {score}): {why[0] if why else 'Underlying ranked for option research.'}")
        if required:
            lines.append(f"   Required before exact contract ranking: {required[0]}")
    return lines


def _sources_section(sources: list[dict]) -> list[str]:
    rows = [source for source in sources if isinstance(source, dict) and source.get("url")]
    if not rows:
        return []
    lines = ["", "Sources:"]
    for index, source in enumerate(rows, start=1):
        title = source.get("title") or source.get("domain") or source.get("url")
        domain = source.get("domain") or ""
        lines.append(f"[{index}] {title} ({domain}) - {source.get('url')}")
    return lines


def _format_assistant_trade_response(response: dict) -> str:
    lines: list[str] = []
    ranking_status = response.get("ranking_status")
    sources = [source for source in _as_list(response.get("research_sources")) if isinstance(source, dict)]
    source_numbers = _source_numbers(sources)
    if response.get("paper_eligible"):
        lines.append("Final paper-eligible ideas passed strict gates. These remain simulated-only.")
    else:
        lines.append("No final paper trades passed strict gates today.")

    if ranking_status == "unavailable":
        lines.append("")
        lines.append("Market ranking is unavailable because usable market data was not returned.")
        lines.append("I am not ranking failed ticker rows as trade ideas. Restore the market-data provider, then rerun the scan.")
    elif ranking_status == "no_qualifying_ideas":
        lines.append("")
        lines.append("The scan had usable data, but no candidates qualified for the assistant ranking buckets.")

    lines.append("")
    lines.extend(_assistant_rows(response.get("paper_eligible", []), "Paper-eligible ideas", source_numbers=source_numbers))
    lines.append("")
    lines.extend(_assistant_rows(response.get("top_stocks", []), "Top stock research ideas", source_numbers=source_numbers))
    option_rows = _as_list(response.get("top_options"))
    option_watchlist = _as_list(response.get("option_underlying_watchlist"))
    lines.append("")
    lines.extend(_option_contract_rows(option_rows, "Paper-eligible option contracts", {"paper_eligible"}))
    lines.append("")
    lines.extend(_option_contract_rows(option_rows, "Research-only option contracts", {"research_only"}))
    lines.append("")
    lines.extend(_option_contract_rows(option_rows, "Blocked option contracts with usable quotes", {"blocked"}))
    if not option_rows and option_watchlist:
        lines.append("")
        lines.extend(_option_underlying_rows(option_watchlist, "Option-underlying watchlist"))
    lines.append("")
    lines.extend(_assistant_rows(response.get("blocked", []), "Blocked ideas", source_numbers=source_numbers))
    lines.append("")
    lines.extend(_bullets("Why no final trades", response.get("why_no_final_trades")))
    lines.append("")
    lines.extend(_bullets("Data missing / system issues", list(response.get("data_missing", [])) + list(response.get("system_issues", []))))
    if response.get("option_data_missing"):
        lines.append("")
        lines.extend(_bullets("Missing option data", response.get("option_data_missing")))
    if response.get("option_discovery_status") not in (None, "", "disabled"):
        lines.append("")
        lines.append(f"Option discovery status: {response.get('option_discovery_status')}. Final option eligibility: {response.get('scan_summary', {}).get('options_final_eligibility', False)}.")
    lines.append("")
    lines.extend(_bullets("What to fix next", response.get("next_steps")))
    if response.get("research_status") in {"available", "partial", "unavailable"} and response.get("research_status") != "not_requested":
        lines.append("")
        if response.get("research_status") == "unavailable":
            lines.append("Current research was requested, but no source-supported evidence was available.")
        elif response.get("research_warnings"):
            lines.extend(_bullets("Research warnings", response.get("research_warnings")))
    lines.extend(_sources_section(sources))
    lines.append("")
    lines.append("Gemini cannot override these deterministic buckets, and blocked/research-only ideas are not trade recommendations.")
    return "\n".join(lines)


def format_best_ideas_response(best_ideas: dict) -> str:
    if not isinstance(best_ideas, dict) or not best_ideas.get("ok"):
        return "I could not build best available ideas from the deterministic backend result."

    if best_ideas.get("response_type") == "trade_ideas":
        return _format_assistant_trade_response(best_ideas)

    lines: list[str] = []
    ranking_status = best_ideas.get("ranking_status")
    if best_ideas.get("paper_eligible"):
        lines.append("Final paper trades passed strict gates. These remain simulated-only.")
    else:
        lines.append("No final paper trades passed strict gates today.")

    if ranking_status == "unavailable":
        lines.append("")
        lines.append("Market ranking is unavailable because the deterministic scan did not return usable market data.")
        lines.append("I am not ranking failed ticker rows as trade ideas. Restore the market-data provider, then rerun the scan.")
        lines.append("")
        lines.extend(_bullets("Why no final trades", best_ideas.get("why_no_final_trades")))
        lines.append("")
        lines.extend(_bullets("Data missing / system issues", list(best_ideas.get("data_missing", [])) + list(best_ideas.get("system_issues", []))))
        lines.append("")
        lines.extend(_bullets("What to fix next", best_ideas.get("next_steps")))
        lines.append("")
        lines.append("Gemini cannot override these deterministic buckets, and blocked/research-only ideas are not trade recommendations.")
        return "\n".join(lines)

    lines.append("")
    lines.extend(_rows(best_ideas.get("paper_eligible", []), "Paper-eligible ideas"))
    lines.append("")
    lines.extend(_rows(best_ideas.get("stock_watchlist", []), "Best stock ideas to watch"))
    lines.append("")
    lines.extend(_rows(best_ideas.get("option_research_only", []), "Best option research ideas"))
    if best_ideas.get("option_underlying_watchlist"):
        lines.append("")
        lines.extend(_option_underlying_rows(best_ideas.get("option_underlying_watchlist", []), "Option-underlying watchlist"))
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
