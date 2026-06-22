from __future__ import annotations

import asyncio
from collections.abc import Callable
import threading
from typing import Any

import anyio


class _WorkerThreadEventLoopPolicy(asyncio.AbstractEventLoopPolicy):
    """Delegate to the active policy, but auto-create loops in worker threads."""

    def __init__(self, base_policy: asyncio.AbstractEventLoopPolicy):
        self._base_policy = base_policy

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        try:
            return self._base_policy.get_event_loop()
        except RuntimeError:
            if threading.current_thread() is threading.main_thread():
                raise
            loop = self.new_event_loop()
            self.set_event_loop(loop)
            return loop

    def set_event_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._base_policy.set_event_loop(loop)

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        return self._base_policy.new_event_loop()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base_policy, name)


def _ensure_worker_thread_event_loop_policy() -> None:
    policy = asyncio.get_event_loop_policy()
    if not isinstance(policy, _WorkerThreadEventLoopPolicy):
        asyncio.set_event_loop_policy(_WorkerThreadEventLoopPolicy(policy))


def _run_with_thread_event_loop(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run sync backend code with an asyncio loop bound to this worker thread.

    ib_insync calls ``asyncio.get_event_loop()`` from synchronous code. AnyIO's
    worker threads do not always have a thread-local loop, so create one only
    inside the worker thread and leave it attached for the duration/lifetime of
    that worker thread.
    """

    _ensure_worker_thread_event_loop_policy()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return func(*args, **kwargs)


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
        _ensure_worker_thread_event_loop_policy()
        if timeout_seconds is None:
            result = await anyio.to_thread.run_sync(
                lambda: _run_with_thread_event_loop(func, *args, **kwargs),
                abandon_on_cancel=True,
            )
        else:
            with anyio.fail_after(timeout_seconds):
                result = await anyio.to_thread.run_sync(
                    lambda: _run_with_thread_event_loop(func, *args, **kwargs),
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
