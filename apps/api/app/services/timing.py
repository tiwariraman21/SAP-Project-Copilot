from __future__ import annotations

import contextvars
import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

_timing_sink: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar("fsd_timing_sink", default=None)


@contextmanager
def timing_session(sink: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    token = _timing_sink.set(sink)
    try:
        yield
    finally:
        _timing_sink.reset(token)


def start_timing_session(sink: Callable[[dict[str, Any]], None]):
    return _timing_sink.set(sink)


def stop_timing_session(token) -> None:
    _timing_sink.reset(token)


def timed(name: str | None = None):
    def decorate(function):
        label = name or function.__qualname__

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            status = "completed"
            try:
                return function(*args, **kwargs)
            except Exception:
                status = "failed"
                raise
            finally:
                sink = _timing_sink.get()
                if sink:
                    sink({"function": label, "duration_ms": round((time.perf_counter() - started) * 1000, 1), "status": status})
        return wrapper
    return decorate
