"""Run blocking work (DB, network, file IO) off the GUI thread.

Results are delivered back on the GUI thread through a QObject that lives
there, so callbacks may touch widgets safely.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)

_active: set["_Relay"] = set()


class _Relay(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(object)

    def __init__(self, owner: QObject | None, on_done, on_error, on_progress):
        super().__init__()  # created on the GUI thread
        self.owner = owner
        self.on_done, self.on_error, self.on_progress = on_done, on_error, on_progress
        self.done.connect(self._handle_done)
        self.failed.connect(self._handle_failed)
        self.progress.connect(self._handle_progress)

    def _alive(self) -> bool:
        return self.owner is None or shiboken6.isValid(self.owner)

    @Slot(object)
    def _handle_done(self, result):
        _active.discard(self)
        if self._alive() and self.on_done:
            self.on_done(result)

    @Slot(object)
    def _handle_failed(self, exc):
        _active.discard(self)
        if not self._alive():
            return
        if self.on_error:
            self.on_error(exc)
        else:
            log.error("Background task failed without handler: %r", exc)

    @Slot(object)
    def _handle_progress(self, value):
        if self._alive() and self.on_progress:
            self.on_progress(value)


class _Task(QRunnable):
    def __init__(self, fn, relay: _Relay, with_progress: bool):
        super().__init__()
        self.fn, self.relay, self.with_progress = fn, relay, with_progress

    def run(self):
        try:
            result = self.fn(self.relay.progress.emit) if self.with_progress else self.fn()
        except Exception as e:  # delivered to the GUI as an error, never swallowed
            if not isinstance(e, _expected_types()):
                log.error("Background task error:\n%s", traceback.format_exc())
            self.relay.failed.emit(e)
        else:
            self.relay.done.emit(result)


def _expected_types():
    from kasaos.core.exceptions import KasaOSError
    return (KasaOSError,)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
              on_error: Callable[[Exception], None] | None = None, owner: QObject | None = None,
              on_progress: Callable[[Any], None] | None = None) -> None:
    """Run fn() in the global thread pool. If on_progress is given, fn receives an emit callback."""
    relay = _Relay(owner, on_done, on_error, on_progress)
    _active.add(relay)
    QThreadPool.globalInstance().start(_Task(fn, relay, on_progress is not None))


def wait_for_all(timeout_ms: int = 10000) -> bool:
    """Used on shutdown so no write is cut off mid-transaction."""
    return QThreadPool.globalInstance().waitForDone(timeout_ms)
