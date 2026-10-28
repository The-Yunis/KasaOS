"""Startup sequence driven from the splash screen.

1. logging (already configured in main) → 2. configuration → 3. services →
4. database access → 5. migrations (backup-protected) → 6. state → 7. window.
Blocking steps run in a worker thread; the splash shows real status text and
turns into an actionable error state on failure.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from kasaos import config
from kasaos.core.application_context import AppContext
from kasaos.core.exceptions import (BackupError, DatabaseCorruptError, DatabaseError, IncompatibleDatabaseError,
                                    MigrationError)
from kasaos.services.update_service import UpdateService
from kasaos.ui.components import show_error
from kasaos.ui.main_window import MainWindow
from kasaos.ui.pages.settings import open_folder
from kasaos.ui.reference import load_reference
from kasaos.ui.splash import SplashScreen
from kasaos.ui.workers import run_async
from kasaos.updates import trust
from kasaos.updates.launcher_core import acknowledge_last_result, write_ready_signal
from kasaos.version import PLATFORM_ID, SCHEMA_VERSION, __version__

log = logging.getLogger(__name__)

UPDATE_CHECK_DELAY_MS = 8000


class Startup(QObject):
    def __init__(self, app: QApplication, paths: config.AppPaths):
        super().__init__()
        self.app, self.paths = app, paths
        self.window: MainWindow | None = None
        self.ctx = AppContext.build(paths)
        self.splash = SplashScreen()
        self.splash.retry_requested.connect(self._retry)
        self.splash.restore_requested.connect(self._restore)
        self.splash.open_logs_requested.connect(lambda: open_folder(paths.logs_dir))
        self.splash.quit_requested.connect(self._quit)

    def start(self):
        self.splash.start()
        self._run()

    def _run(self):
        def steps(emit):
            emit("Veritabanı kontrol ediliyor…")
            self.ctx.open_database()
            emit("Ayarlar yükleniyor…")
            notes = []
            try:
                self.ctx.auto_backup()
            except BackupError as e:  # not fatal, but reported
                log.error("Automatic backup failed: %s", e)
                notes.append(f"Otomatik yedek alınamadı: {e}")
            ref = load_reference(self.ctx)
            business = self.ctx.settings.get("business_name")
            check_updates = self.ctx.settings.get_bool("update_check_on_start")
            return ref, business, check_updates, notes
        run_async(steps, self._ready, self._failed, owner=self, on_progress=self.splash.set_status)

    def _ready(self, result):
        ref, business, check_updates, notes = result
        self.splash.set_status("Arayüz hazırlanıyor…")
        updates = UpdateService(
            current_version=__version__, app_schema=SCHEMA_VERSION, platform=PLATFORM_ID,
            updates_dir=self.paths.updates_dir, install_root=config.install_root(),
            public_keys=list(trust.TRUSTED_PUBLIC_KEYS),
            source=lambda: (self.ctx.settings.get("update_owner"), self.ctx.settings.get("update_repo"),
                            self.ctx.settings.get_bool("update_allow_prerelease")),
            backup_fn=lambda reason: self.ctx.backups.create(reason))
        self.window = MainWindow(self.ctx, updates, ref, business)
        self.window.show()
        self.splash.spinner.stop()
        self.splash.close()
        log.info("Main window shown (KasaOS %s)", __version__)
        QTimer.singleShot(0, self._signal_ready)
        for n in notes:
            self.window.notify(n, "error")
        notice = os.environ.get(config.ENV_UPDATE_NOTICE)
        if notice:
            QTimer.singleShot(300, lambda: self._show_notice(notice))
        if check_updates:
            QTimer.singleShot(UPDATE_CHECK_DELAY_MS, lambda: self.window and self.window.check_updates(False))

    def _signal_ready(self):
        """Readiness signal for the launcher: DB open, migrated, window visible."""
        path = os.environ.get(config.ENV_READY_FILE)
        if not path:
            return
        try:
            write_ready_signal(Path(path), __version__)
            log.info("Readiness signal written")
        except OSError:
            log.exception("Could not write readiness signal")

    def _show_notice(self, notice: str):
        self.window.show_update_notice(notice)
        root = config.install_root()
        if root:
            try:
                acknowledge_last_result(root)
            except OSError:
                log.exception("Could not acknowledge update result")

    def _failed(self, exc: Exception):
        log.error("Startup failed: %r", exc, exc_info=exc)
        can_restore = isinstance(exc, (DatabaseCorruptError, MigrationError, IncompatibleDatabaseError))
        if isinstance(exc, DatabaseCorruptError):
            title = "Veritabanı açılamadı"
            text = (f"{exc}\n\nVeritabanı dosyanız silinmedi veya değiştirilmedi. Bir yedekten geri "
                    f"yükleyebilir ya da destek için günlük dosyalarını paylaşabilirsiniz.")
        elif isinstance(exc, MigrationError):
            title = "Veritabanı güncellemesi başarısız"
            text = f"{exc}\n\nVerileriniz korunuyor." + (f"\nGüncelleme öncesi yedek: {exc.backup_path}"
                                                          if exc.backup_path else "")
        elif isinstance(exc, IncompatibleDatabaseError):
            title = "Uyumsuz veritabanı"
            text = f"{exc}\n\nKasaOS'un daha yeni bir sürümünü kurun veya uyumlu bir yedeği geri yükleyin."
        elif isinstance(exc, DatabaseError):
            title = "Veritabanı hatası"
            text = str(exc)
        else:
            title = "KasaOS başlatılamadı"
            text = f"Beklenmeyen hata: {type(exc).__name__}: {exc}\nAyrıntılar günlük dosyasında."
        self.splash.show_error(title, text, can_restore)

    def _retry(self):
        self.ctx.db.close()
        self.splash.reset()
        self.splash.set_status("Tekrar deneniyor…")
        self._run()

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self.splash, "Geri yüklenecek yedeği seçin", str(self.paths.backups_dir),
                                              "KasaOS yedeği (*.kasaosbak *.db);;Tüm dosyalar (*)")
        if not path:
            return
        self.ctx.db.close()
        self.splash.reset()
        self.splash.set_status("Yedek doğrulanıyor ve geri yükleniyor…")
        run_async(lambda: self.ctx.backups.restore(Path(path), SCHEMA_VERSION),
                  lambda safety: (log.warning("Restored at startup; original kept at %s", safety), self._run()),
                  lambda e: (show_error(self.splash, "Geri yükleme başarısız", e), self._failed(e)), owner=self)

    def _quit(self):
        self.ctx.shutdown()
        self.splash.close()
        self.app.quit()
