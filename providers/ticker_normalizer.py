from __future__ import annotations


IBKR_CLASS_SHARE_MAP = {
    "BRK.B": "BRK B",
    "BRK-B": "BRK B",
    "BRK B": "BRK B",
    "BF.B": "BF B",
    "BF-B": "BF B",
    "BF B": "BF B",
}


def normalize_ticker_for_provider(
    ticker: str,
    provider: str,
) -> dict:
    original = str(ticker or "").strip().upper()
    normalized_provider = str(provider or "").strip().lower()
    warnings: list[str] = []
    if not original:
        return {
            "ok": False,
            "original_ticker": ticker,
            "normalized_ticker": None,
            "provider": normalized_provider,
            "warnings": warnings,
            "error": "Ticker symbol is empty.",
        }

    normalized = " ".join(original.replace("/", " ").split())
    if normalized_provider == "ibkr":
        compact_key = normalized.replace(" ", ".")
        dash_key = normalized.replace(" ", "-")
        if normalized in IBKR_CLASS_SHARE_MAP:
            normalized = IBKR_CLASS_SHARE_MAP[normalized]
        elif compact_key in IBKR_CLASS_SHARE_MAP:
            normalized = IBKR_CLASS_SHARE_MAP[compact_key]
        elif dash_key in IBKR_CLASS_SHARE_MAP:
            normalized = IBKR_CLASS_SHARE_MAP[dash_key]
        if normalized != original:
            warnings.append(f"Normalized {original} to {normalized} for IBKR class-share lookup.")

    return {
        "ok": True,
        "original_ticker": original,
        "normalized_ticker": normalized,
        "provider": normalized_provider,
        "warnings": warnings,
        "error": None,
    }

