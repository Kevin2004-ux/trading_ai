from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScanState:
    """Serializable state tracker for bounded ticker scans."""

    def __init__(self, tickers: list[str]):
        normalized = [str(ticker).strip().upper() for ticker in tickers or []]
        self.pending_tickers: set[str] = set(normalized)
        self.in_progress_tickers: set[str] = set()
        self.completed_tickers: set[str] = set()
        self.failed_tickers: set[str] = set()
        self.timed_out_tickers: set[str] = set()
        self.skipped_tickers: set[str] = set()
        self.started_at = _now_iso()
        self.completed_at: str | None = None
        self.warnings: list[str] = []
        self.errors: list[dict] = []

    def mark_started(self, ticker: str) -> None:
        normalized = str(ticker).strip().upper()
        self.pending_tickers.discard(normalized)
        self.in_progress_tickers.add(normalized)

    def mark_completed(self, ticker: str) -> None:
        normalized = str(ticker).strip().upper()
        self.in_progress_tickers.discard(normalized)
        self.pending_tickers.discard(normalized)
        self.completed_tickers.add(normalized)

    def mark_failed(self, ticker: str, error: str) -> None:
        normalized = str(ticker).strip().upper()
        self.in_progress_tickers.discard(normalized)
        self.pending_tickers.discard(normalized)
        self.failed_tickers.add(normalized)
        self.errors.append({"ticker": normalized, "type": "failure", "message": str(error)})

    def mark_timed_out(self, ticker: str, error: str | None = None) -> None:
        normalized = str(ticker).strip().upper()
        self.in_progress_tickers.discard(normalized)
        self.pending_tickers.discard(normalized)
        self.timed_out_tickers.add(normalized)
        self.errors.append(
            {
                "ticker": normalized,
                "type": "timeout",
                "message": error or f"{normalized} timed out during scan.",
            }
        )

    def mark_skipped(self, ticker: str, reason: str) -> None:
        normalized = str(ticker).strip().upper()
        self.in_progress_tickers.discard(normalized)
        self.pending_tickers.discard(normalized)
        self.skipped_tickers.add(normalized)
        self.warnings.append(f"{normalized}: {reason}")

    def add_warning(self, warning: str) -> None:
        self.warnings.append(str(warning))

    def complete(self) -> None:
        self.completed_at = _now_iso()

    def summary(self) -> dict[str, Any]:
        return {
            "pending_tickers": sorted(self.pending_tickers),
            "in_progress_tickers": sorted(self.in_progress_tickers),
            "completed_tickers": sorted(self.completed_tickers),
            "failed_tickers": sorted(self.failed_tickers),
            "timed_out_tickers": sorted(self.timed_out_tickers),
            "skipped_tickers": sorted(self.skipped_tickers),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

