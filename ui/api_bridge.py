from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import anyio


def _run_with_worker_event_loop(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    created_loop = False
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
        created_loop = True

    try:
        return func(*args, **kwargs)
    finally:
        if created_loop:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.close()
                asyncio.set_event_loop(None)


async def run_blocking_backend_call(
    func: Callable[..., Any],
    *args: Any,
    timeout_seconds: int | None = None,
    **kwargs: Any,
) -> dict:
    """Run synchronous backend work outside FastAPI's event loop.

    IBKR/ib_insync and several trading engine paths manage their own event-loop
    state. Running them directly inside an async FastAPI route can raise
    "Cannot run the event loop while another loop is running". Keep those calls
    isolated in a worker thread and normalize failures for the frontend.
    """

    try:
        if timeout_seconds is None:
            result = await anyio.to_thread.run_sync(
                lambda: _run_with_worker_event_loop(func, *args, **kwargs),
                abandon_on_cancel=True,
            )
        else:
            with anyio.fail_after(timeout_seconds):
                result = await anyio.to_thread.run_sync(
                    lambda: _run_with_worker_event_loop(func, *args, **kwargs),
                    abandon_on_cancel=True,
                )
    except TimeoutError:
        return {
            "ok": False,
            "error": f"Backend call timed out after {timeout_seconds} seconds.",
            "error_type": "TimeoutError",
            "source": "api_bridge",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "source": "api_bridge",
        }

    if isinstance(result, dict):
        return result

    return {
        "ok": True,
        "data": result,
        "source": "api_bridge",
    }
