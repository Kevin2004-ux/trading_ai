from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import re
from typing import Any


INTENT_CONSTRAINTS_VERSION = "intent_constraints_v1"

_NO_OPTIONS_TERMS = (
    "stock only",
    "stocks only",
    "equities only",
    "equity only",
    "do not include options",
    "don't include options",
    "no options",
    "without options",
    "exclude options",
)
_OPTION_TERMS = ("option", "options", "call", "calls", "put", "puts", "spread", "spreads", "premium")
_BOTH_TERMS = ("stocks and options", "stock and option", "equities and options", "both stocks and options")
_STOCK_TERMS = ("stock", "stocks", "equity", "equities", "shares")
_EARNINGS_TERMS = ("earnings", "earnings this week", "upcoming earnings", "earnings calendar")
_NEWS_TERMS = ("news", "headline", "headlines", "developments")
_FILING_TERMS = ("filing", "filings", "sec", "8-k", "form 4", "insider")
_CATALYST_TERMS = ("catalyst", "catalysts", "event", "events")


@dataclass
class IntentConstraints:
    requested_instrument: str = "stocks"
    catalyst_types: list[str] = field(default_factory=list)
    max_option_premium: float | None = None
    min_stock_price: float | None = None
    max_stock_price: float | None = None
    preferred_market_cap_style: str | None = None
    earnings_window_days: int | None = None
    min_dte: int | None = None
    max_dte: int | None = None
    risk_style: str = "balanced"
    allow_small_cap: bool = False
    require_upcoming_earnings: bool = False
    require_catalyst: bool = False
    strategy_profile: str = "default_swing"
    external_discovery_requested: bool = False
    source: str = "deterministic_parser"
    parser_version: str = INTENT_CONSTRAINTS_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["catalyst_types"] = _unique_texts(payload.get("catalyst_types"))
        return payload


def _normalize_text(message: str) -> str:
    return re.sub(r"\s+", " ", str(message or "").lower().replace("-", " ")).strip()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.replace("-", " ") in text for term in terms)


def _unique_texts(values: list[Any] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric >= 0 else None


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else None


def _money_after_patterns(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _safe_float(match.group(1))
    return None


def _extract_option_premium(text: str) -> float | None:
    explicit = _money_after_patterns(
        text,
        (
            r"(?:options?|calls?|puts?).{0,35}(?:under|below|less than|max(?:imum)?|up to)\s*\$?([0-9]+(?:\.[0-9]+)?)",
            r"(?:under|below|less than|max(?:imum)?|up to)\s*\$?([0-9]+(?:\.[0-9]+)?).{0,25}(?:premium|debit|options?|calls?|puts?)",
            r"(?:premium|debit).{0,20}(?:under|below|less than|max(?:imum)?|up to)\s*\$?([0-9]+(?:\.[0-9]+)?)",
        ),
    )
    if explicit is not None:
        return explicit
    if "cheap option" in text or "cheap options" in text:
        return 250.0
    return None


def _extract_stock_price_bounds(text: str, requested_instrument: str) -> tuple[float | None, float | None]:
    max_price = _money_after_patterns(
        text,
        (
            r"(?:stocks?|shares?|equities?).{0,35}(?:under|below|less than|max(?:imum)?|up to)\s*\$?([0-9]+(?:\.[0-9]+)?)",
            r"(?:under|below|less than|max(?:imum)?|up to)\s*\$?([0-9]+(?:\.[0-9]+)?).{0,25}(?:stocks?|shares?|equities?)",
        ),
    )
    if max_price is None and requested_instrument != "options":
        max_price = _money_after_patterns(
            text,
            (r"(?:small cap|small caps|penny|momentum).{0,35}(?:under|below|less than|max(?:imum)?|up to)\s*\$?([0-9]+(?:\.[0-9]+)?)",),
        )
    min_price = _money_after_patterns(
        text,
        (
            r"(?:stocks?|shares?|equities?).{0,35}(?:over|above|more than|min(?:imum)?|at least)\s*\$?([0-9]+(?:\.[0-9]+)?)",
            r"(?:over|above|more than|min(?:imum)?|at least)\s*\$?([0-9]+(?:\.[0-9]+)?).{0,25}(?:stocks?|shares?|equities?)",
        ),
    )
    return min_price, max_price


def _extract_dte(text: str) -> tuple[int | None, int | None]:
    range_match = re.search(r"([0-9]{1,3})\s*(?:-|to)\s*([0-9]{1,3})\s*(?:dte|days? to expiration|days?)", text)
    if range_match:
        left = _safe_int(range_match.group(1))
        right = _safe_int(range_match.group(2))
        if left is not None and right is not None:
            return min(left, right), max(left, right)
    max_match = re.search(r"(?:under|below|less than|max(?:imum)?|up to)\s*([0-9]{1,3})\s*(?:dte|days? to expiration|days?)", text)
    if max_match:
        return None, _safe_int(max_match.group(1))
    min_match = re.search(r"(?:over|above|more than|min(?:imum)?|at least)\s*([0-9]{1,3})\s*(?:dte|days? to expiration|days?)", text)
    if min_match:
        return _safe_int(min_match.group(1)), None
    return None, None


def _requested_instrument(text: str, planner_intent: dict[str, Any] | None = None) -> str:
    planner_requested = str((planner_intent or {}).get("requested_instrument") or "").strip().lower()
    if _has_any(text, _NO_OPTIONS_TERMS):
        return "stocks"
    if _has_any(text, _BOTH_TERMS):
        return "both"
    if _has_any(text, _OPTION_TERMS):
        return "options"
    if planner_requested in {"stocks", "options", "both"}:
        return planner_requested
    if _has_any(text, _STOCK_TERMS):
        return "stocks"
    return "stocks"


def _risk_style(text: str) -> str:
    if any(term in text for term in ("aggressive", "high risk", "speculative")):
        return "aggressive"
    if any(term in text for term in ("safe", "conservative", "safer", "lower risk", "low risk")):
        return "conservative"
    return "balanced"


def _catalyst_types(text: str) -> list[str]:
    types: list[str] = []
    if _has_any(text, _EARNINGS_TERMS):
        types.append("earnings")
    if _has_any(text, _NEWS_TERMS):
        types.append("news")
    if _has_any(text, _FILING_TERMS):
        if "form 4" in text or "insider" in text:
            types.append("insider")
        types.append("filings")
    if "analyst" in text or "upgrade" in text or "downgrade" in text:
        types.append("analyst")
    if "momentum" in text or "relative volume" in text or "volume" in text:
        types.append("momentum")
    if _has_any(text, _CATALYST_TERMS) and not types:
        types.append("news")
    return _unique_texts(types)


def _earnings_window_days(text: str, require_upcoming_earnings: bool) -> int | None:
    if "this week" in text:
        return 7
    if "next week" in text:
        return 14
    match = re.search(r"(?:earnings|catalysts?).{0,20}(?:next|within)\s*([0-9]{1,2})\s*days?", text)
    if match:
        return max(1, min(_safe_int(match.group(1)) or 14, 60))
    return 14 if require_upcoming_earnings else None


def _strategy_profile(
    *,
    requested_instrument: str,
    catalyst_types: list[str],
    allow_small_cap: bool,
    require_upcoming_earnings: bool,
    risk_style: str,
) -> str:
    if requested_instrument == "options" and require_upcoming_earnings:
        return "earnings_options"
    if allow_small_cap and risk_style == "aggressive":
        return "small_cap_momentum"
    if catalyst_types:
        return "catalyst_watchlist"
    if risk_style == "conservative":
        return "conservative_large_cap"
    return "default_swing"


def extract_intent_constraints(message: str, planner_intent: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _normalize_text(message)
    requested = _requested_instrument(text, planner_intent=planner_intent)
    catalyst_types = _catalyst_types(text)
    require_upcoming_earnings = _has_any(text, _EARNINGS_TERMS) and any(term in text for term in ("upcoming", "this week", "next week", "within", "calendar"))
    require_catalyst = bool(catalyst_types or _has_any(text, _CATALYST_TERMS))
    risk_style = _risk_style(text)
    allow_small_cap = any(term in text for term in ("small cap", "small caps", "micro cap", "microcap", "penny"))
    market_cap_style = "small_cap" if allow_small_cap else "large_cap" if risk_style == "conservative" else None
    min_stock_price, max_stock_price = _extract_stock_price_bounds(text, requested)
    min_dte, max_dte = _extract_dte(text)
    max_option_premium = _extract_option_premium(text) if requested in {"options", "both"} or "premium" in text else None
    earnings_window = _earnings_window_days(text, require_upcoming_earnings)
    profile = _strategy_profile(
        requested_instrument=requested,
        catalyst_types=catalyst_types,
        allow_small_cap=allow_small_cap,
        require_upcoming_earnings=require_upcoming_earnings,
        risk_style=risk_style,
    )
    external_requested = bool(require_catalyst or require_upcoming_earnings or allow_small_cap or profile in {"earnings_options", "catalyst_watchlist"})

    return IntentConstraints(
        requested_instrument=requested,
        catalyst_types=catalyst_types,
        max_option_premium=max_option_premium,
        min_stock_price=min_stock_price,
        max_stock_price=max_stock_price,
        preferred_market_cap_style=market_cap_style,
        earnings_window_days=earnings_window,
        min_dte=min_dte,
        max_dte=max_dte,
        risk_style=risk_style,
        allow_small_cap=allow_small_cap,
        require_upcoming_earnings=require_upcoming_earnings,
        require_catalyst=require_catalyst,
        strategy_profile=profile,
        external_discovery_requested=external_requested,
    ).to_dict()


def apply_intent_constraints_to_plan(plan: dict[str, Any], constraints: dict[str, Any] | None) -> dict[str, Any]:
    updated = deepcopy(plan or {})
    intent = constraints if isinstance(constraints, dict) else {}
    requested = str(intent.get("requested_instrument") or updated.get("requested_instrument") or "stocks").lower()

    if requested in {"stocks", "options", "both"}:
        updated["requested_instrument"] = requested
    if requested == "stocks":
        updated["include_options"] = False
        updated["prefer_options"] = False
    elif requested == "options":
        updated["include_options"] = True
        updated["prefer_options"] = True
    elif requested == "both":
        updated["include_options"] = True

    option_preferences = deepcopy(updated.get("option_preferences") or {})
    if intent.get("max_option_premium") is not None:
        option_preferences["max_option_premium"] = intent["max_option_premium"]
    if intent.get("min_dte") is not None:
        option_preferences["min_dte"] = intent["min_dte"]
    if intent.get("max_dte") is not None:
        option_preferences["max_dte"] = intent["max_dte"]
    updated["option_preferences"] = option_preferences

    soft = deepcopy(updated.get("soft_adjustments") or {})
    for source_key, target_key in (
        ("min_stock_price", "min_stock_price"),
        ("max_stock_price", "max_stock_price"),
    ):
        if intent.get(source_key) is not None:
            soft[target_key] = intent[source_key]
    updated["soft_adjustments"] = soft

    research_preferences = deepcopy(updated.get("research_preferences") or {})
    catalyst_types = set(intent.get("catalyst_types") or [])
    if "news" in catalyst_types or intent.get("require_catalyst"):
        research_preferences["include_news"] = True
    if "filings" in catalyst_types or "insider" in catalyst_types:
        research_preferences["include_sec_filings"] = True
    if "earnings" in catalyst_types or intent.get("require_upcoming_earnings"):
        research_preferences["include_earnings_transcripts"] = True
    updated["research_preferences"] = research_preferences
    if intent.get("require_catalyst") or catalyst_types:
        updated["include_catalysts"] = True

    if not updated.get("custom_tickers"):
        profile = str(intent.get("strategy_profile") or "default_swing")
        risk_style = str(intent.get("risk_style") or "balanced")
        if profile == "small_cap_momentum":
            updated["universes"] = ["active", "growth"]
            updated["profiles"] = ["catalyst_watch", "momentum_breakout", "oversold_reversal"]
        elif profile == "earnings_options":
            updated["universes"] = ["large_cap", "active", "growth"]
            updated["profiles"] = ["catalyst_watch", "momentum_breakout", "relative_strength"]
        elif profile == "catalyst_watchlist":
            updated["profiles"] = ["catalyst_watch", "momentum_breakout", "trend_pullback"]
        elif risk_style == "conservative":
            updated["universes"] = ["mega_cap", "large_cap"]
            updated["profiles"] = ["momentum_breakout", "relative_strength", "trend_pullback"]

    updated["user_intent"] = intent
    return updated
