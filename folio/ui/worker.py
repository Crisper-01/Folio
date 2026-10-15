"""Run CPU heavy PDF work in a separate process so the UI stays responsive."""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Any

from PySide6.QtCore import QObject, QTimer

_pool: ProcessPoolExecutor | None = None


def pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    return _pool


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


class Job(QObject):
    """Submit ``fn(*args)`` to the worker process and call back on the GUI thread."""

    def __init__(
        self, fn: Callable, *args: Any, on_done: Callable[[Any], None], on_error: Callable[[BaseException], None], parent=None
    ) -> None:
        super().__init__(parent)
        self.cancelled = False
        self._on_done, self._on_error = on_done, on_error
        self._future: Future = pool().submit(fn, *args)
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def cancel(self) -> None:
        self.cancelled = True
        self._future.cancel()
        self._timer.stop()

    def _poll(self) -> None:
        if not self._future.done():
            return
        self._timer.stop()
        if self.cancelled or self._future.cancelled():
            return
        err = self._future.exception()
        if err is not None:
            self._on_error(err)
        else:
            self._on_done(self._future.result())
