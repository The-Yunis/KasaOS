"""KasaOS entry point. Coded by Yunus Açıkgöz"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile, QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from kasaos import config
from kasaos.core.logging_config import configure_logging, install_exception_hooks
from kasaos.version import APP_NAME, __version__

log = logging.getLogger("kasaos")


class _ErrorReporter(QObject):
    """Marshals unhandled exceptions from any thread to one dialog on the GUI thread."""
    report = Signal(str)

    def __init__(self):
        super().__init__()
        self._showing = False
        self.report.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def _show(self, text: str):
        if self._showing:
            return
        self._showing = True
        try:
            box = QMessageBox(QMessageBox.Icon.Critical, "Beklenmeyen hata",
                              "Beklenmeyen bir hata oluştu. Son işlem tamamlanmamış olabilir; kayıtlarınızı "
                              "kontrol edin.\nAyrıntılar günlük dosyasına kaydedildi.")
            box.setDetailedText(text)
            box.exec()
        finally:
            self._showing = False


def main(argv: list[str] | None = None) -> int:
    paths = config.default_paths()
    paths.ensure()
    log_file = configure_logging(paths.logs_dir)
    log.info("KasaOS %s starting (python %s, frozen=%s)", __version__, sys.version.split()[0],
             getattr(sys, "frozen", False))
    log.info("Data root: %s; install root: %s", paths.root, config.install_root())

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationName(APP_NAME)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setFont(QFont("Segoe UI", 10))

    from kasaos.ui import icons, theme
    app.setWindowIcon(icons.app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())

    reporter = _ErrorReporter()
    install_exception_hooks(lambda t, e, tb: reporter.report.emit(f"{t.__name__}: {e}\n\nGünlük: {log_file}"))

    # Single instance: two copies would race on the database and on updates.
    lock = QLockFile(str(paths.root / "kasaos.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(500):
        log.warning("Another instance is running")
        QMessageBox.information(None, APP_NAME, "KasaOS zaten açık.")
        return 0

    from kasaos.bootstrap import Startup
    startup = Startup(app, paths)
    startup.start()
    try:
        code = app.exec()
    finally:
        lock.unlock()
        log.info("KasaOS exited")
    return code


if __name__ == "__main__":
    sys.exit(main())
