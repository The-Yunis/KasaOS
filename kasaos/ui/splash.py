"""Startup splash: brand, real status text, a native spinner, and an error state."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from kasaos.ui import icons, theme
from kasaos.ui.components import Spinner, button, label
from kasaos.version import APP_SPLASH_TAGLINE, DEVELOPER_CREDIT, __version__


class SplashScreen(QWidget):
    retry_requested = Signal()
    restore_requested = Signal()
    open_logs_requested = Signal()
    quit_requested = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(440, 300)
        frame = QFrame(self)
        frame.setObjectName("SplashFrame")
        frame.setStyleSheet(f"#SplashFrame {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER_STRONG};"
                            f" border-radius: 14px; }}")
        frame.setGeometry(0, 0, 440, 300)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(30, 28, 30, 20)
        lay.setSpacing(6)
        top = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icons.brand_pixmap(56, background=False))
        top.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        word = label(f'Kasa<span style="color:{theme.GOLD}">OS</span>')
        word.setStyleSheet("font-size: 22pt; font-weight: 600;")
        names.addWidget(word)
        names.addWidget(label(APP_SPLASH_TAGLINE, "Muted"))
        top.addLayout(names, 1)
        lay.addLayout(top)
        lay.addStretch(1)

        self.status_row = QHBoxLayout()
        self.spinner = Spinner(22)
        self.status = label("Uygulama hazırlanıyor…", "Muted", wrap=True)
        self.status_row.addWidget(self.spinner)
        self.status_row.addWidget(self.status, 1)
        lay.addLayout(self.status_row)

        self.error_box = QWidget()
        eb = QVBoxLayout(self.error_box)
        eb.setContentsMargins(0, 0, 0, 0)
        self.error_title = label("", wrap=True)
        self.error_title.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        self.error_text = label("", "Muted", wrap=True)
        eb.addWidget(self.error_title)
        eb.addWidget(self.error_text)
        btns = QHBoxLayout()
        self.restore_btn = button("Yedekten geri yükle…")
        self.restore_btn.clicked.connect(self.restore_requested)
        logs = button("Günlükler")
        logs.clicked.connect(self.open_logs_requested)
        retry = button("Tekrar dene")
        retry.clicked.connect(self.retry_requested)
        quit_ = button("Kapat", "Primary")
        quit_.clicked.connect(self.quit_requested)
        for b in (self.restore_btn, logs, retry):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(quit_)
        eb.addLayout(btns)
        self.error_box.hide()
        lay.addWidget(self.error_box)

        lay.addSpacing(8)
        foot = QHBoxLayout()
        foot.addWidget(label(DEVELOPER_CREDIT, "Faint"))
        foot.addStretch(1)
        foot.addWidget(label(f"v{__version__}", "Faint"))
        lay.addLayout(foot)
        self._center()

    def _center(self):
        screen = QGuiApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    def start(self):
        self.show()
        self.spinner.start()

    def set_status(self, text: str):
        self.status.setText(text)

    def show_error(self, title: str, text: str, can_restore: bool):
        """Replace the spinner with an actionable error state (never an endless spinner)."""
        self.spinner.stop()
        self.status.hide()
        self.setFixedSize(520, 360)
        self.findChild(QFrame, "SplashFrame").setGeometry(0, 0, 520, 360)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.error_title.setText(title)
        self.error_text.setText(text)
        self.restore_btn.setVisible(can_restore)
        self.error_box.show()
        self._center()
        self.show()

    def reset(self):
        self.error_box.hide()
        self.status.show()
        self.spinner.start()
