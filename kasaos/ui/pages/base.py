from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from kasaos.ui.components import show_error
from kasaos.ui.workers import run_async

if TYPE_CHECKING:
    from kasaos.ui.main_window import MainWindow


class Page(QWidget):
    """Base page: loads its data off the GUI thread whenever it becomes stale."""

    title = ""
    scrollable = True

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window_ = window
        self.ctx = window.ctx
        self.setObjectName("Page")
        self._stale = True
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setObjectName("Page")
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(32, 26, 32, 26)
        self.content.setSpacing(18)
        if self.scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(inner)
            outer.addWidget(scroll)
        else:
            outer.addWidget(inner)

    # override
    def params(self):
        """Runs on the GUI thread: snapshot widget values needed by load()."""
        return None

    def load(self, params):
        """Runs in a worker thread (must not touch widgets); return data for apply()."""
        return None

    def apply(self, data):
        pass

    def mark_stale(self):
        self._stale = True
        if self.isVisible():
            self.refresh()

    def refresh(self):
        if self._loading:
            self._stale = True
            return
        self._loading = True
        self._stale = False
        params = self.params()
        run_async(lambda: self.load(params), self._applied, self._failed, owner=self)

    def _applied(self, data):
        self._loading = False
        self.apply(data)
        if self._stale:
            self.refresh()

    def _failed(self, exc):
        self._loading = False
        show_error(self, "Veriler yüklenemedi", exc)

    def showEvent(self, event):
        super().showEvent(event)
        if self._stale:
            self.refresh()
