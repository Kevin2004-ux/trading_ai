from pipeline.scan_state import ScanState


def test_scan_state_summary_serializes_cleanly():
    state = ScanState(["AAPL", "MSFT", ""])
    state.mark_started("AAPL")
    state.mark_completed("AAPL")
    state.mark_started("MSFT")
    state.mark_timed_out("MSFT", "MSFT timed out.")
    state.mark_skipped("UNKNOWN", "empty ticker")
    state.complete()

    summary = state.summary()

    assert summary["completed_tickers"] == ["AAPL"]
    assert summary["timed_out_tickers"] == ["MSFT"]
    assert summary["skipped_tickers"] == ["UNKNOWN"]
    assert summary["completed_at"] is not None
    assert summary["errors"][0]["type"] == "timeout"
    assert summary["warnings"]

