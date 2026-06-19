import time

import anyio

from ui.api_bridge import run_blocking_backend_call


def test_run_blocking_backend_call_returns_dict_result():
    result = anyio.run(run_blocking_backend_call, lambda value: {"ok": True, "value": value}, "ready")

    assert result == {"ok": True, "value": "ready"}


def test_run_blocking_backend_call_wraps_non_dict_result():
    result = anyio.run(run_blocking_backend_call, lambda: ["AAPL"])

    assert result["ok"] is True
    assert result["data"] == ["AAPL"]
    assert result["source"] == "api_bridge"


def test_run_blocking_backend_call_catches_exceptions():
    def explode():
        raise RuntimeError("provider unavailable")

    result = anyio.run(run_blocking_backend_call, explode)

    assert result["ok"] is False
    assert result["error"] == "provider unavailable"
    assert result["error_type"] == "RuntimeError"
    assert result["source"] == "api_bridge"


def test_run_blocking_backend_call_times_out_cleanly():
    async def call():
        return await run_blocking_backend_call(time.sleep, 0.2, timeout_seconds=0.01)

    result = anyio.run(call)

    assert result["ok"] is False
    assert result["error_type"] == "TimeoutError"
    assert result["source"] == "api_bridge"
