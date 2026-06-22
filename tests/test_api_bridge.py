import time
import asyncio
import threading

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


def test_run_blocking_backend_call_provides_event_loop_in_worker_thread():
    def needs_event_loop():
        loop = asyncio.get_event_loop()
        return {
            "ok": True,
            "loop_closed": loop.is_closed(),
            "thread_name": threading.current_thread().name,
        }

    result = anyio.run(run_blocking_backend_call, needs_event_loop)

    assert result["ok"] is True
    assert result["loop_closed"] is False
    assert result["thread_name"] != "MainThread"


def test_run_blocking_backend_call_provides_event_loop_in_nested_worker_thread():
    def backend_with_nested_thread():
        nested_result = {}

        def nested_worker():
            loop = asyncio.get_event_loop()
            nested_result["loop_closed"] = loop.is_closed()
            nested_result["thread_name"] = threading.current_thread().name

        thread = threading.Thread(target=nested_worker, name="asyncio_0")
        thread.start()
        thread.join(timeout=2)
        return {"ok": True, **nested_result}

    result = anyio.run(run_blocking_backend_call, backend_with_nested_thread)

    assert result["ok"] is True
    assert result["loop_closed"] is False
    assert result["thread_name"] == "asyncio_0"


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
