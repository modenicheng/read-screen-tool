"""Lightweight signal/slot mechanism for non-Qt code.

Provides Signal (callback list) and SignalSpy (test helper) as simple
callback-based alternatives to PySide6 Signal and QSignalSpy.
``safe_emit()`` marshals callbacks to the tkinter main thread for
thread-safe cross-thread signal emission.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class Signal:
    """Callback-based signal. Supports .connect(), .disconnect(), .emit().

    ``emit()`` invokes callbacks synchronously on the calling thread.
    Use ``safe_emit()`` when calling from a background thread — it
    marshals the callback to the tkinter main thread via ``after_idle()``.
    """

    def __init__(self, *param_types: type) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)

    def disconnect(self, callback: Callable[..., None] | None = None) -> None:
        if callback is None:
            self._callbacks.clear()
        elif callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, *args: Any) -> None:
        for cb in self._callbacks:
            cb(*args)

    def safe_emit(self, *args: Any) -> None:
        """Thread-safe emission — schedules emit() on tkinter's main thread.

        Use when emitting from a background thread to avoid tkinter
        thread-safety violations in connected callbacks.
        """
        from overlay import _get_root

        root = _get_root()
        root.after_idle(lambda: self.emit(*args))


class SignalSpy:
    """Test helper — records signal emissions. Replaces QSignalSpy."""

    def __init__(self, signal: Signal) -> None:
        self._calls: list[tuple[Any, ...]] = []
        signal.connect(self._record)
        self._signal = signal

    def _record(self, *args: Any) -> None:
        self._calls.append(args)

    def count(self) -> int:
        return len(self._calls)

    def at(self, index: int) -> tuple[Any, ...]:
        return self._calls[index]

    def disconnect(self) -> None:
        self._signal.disconnect(self._record)
