"""Update dialog: versions, notes, download/verify/stage progress, restart handoff.

It never reports success itself: success is only shown after the launcher has
switched versions and the new version started (see MainWindow update notice).
"""

from __future__ import annotations

import threading

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QProgressBar, QVBoxLayout

from kasaos.services.update_service import UpdateCheck, UpdateService
from kasaos.ui import theme
from kasaos.ui.components import button, confirm, label
from kasaos.ui.workers import run_async

STAGES = {"download": "İndiriliyor…", "verify": "Bütünlük doğrulanıyor (SHA-256)…",
          "stage": "Yeni sürüm ayrı klasöre hazırlanıyor…", "backup": "Veritabanı yedekleniyor…",
          "ready": "Hazır. Yeniden başlatıldığında yeni sürüm denenecek."}


class UpdateDialog(QDialog):
    def __init__(self, service: UpdateService, check: UpdateCheck, current_version: str, on_restart, parent=None):
        super().__init__(parent)
        self.service, self.check, self.on_restart = service, check, on_restart
        self._cancel = threading.Event()
        self._busy = False
        m = check.manifest
        self.setWindowTitle("KasaOS Güncellemesi")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(f"KasaOS {m.version} kullanılabilir", "SectionTitle"))
        lay.addWidget(label(f"Kurulu sürüm: {current_version}   →   Yeni sürüm: {m.version}", "Muted"))
        notes = QPlainTextEdit(m.notes or check.release.body or "Sürüm notu yok.")
        notes.setReadOnly(True)
        notes.setMaximumHeight(180)
        lay.addWidget(notes)
        if check.previously_failed:
            lay.addWidget(self._warn(f"Bu sürüm daha önce başlatılamadı ve geri alındı: {check.previously_failed}. "
                                     "Tekrar denemek isterseniz devam edebilirsiniz."))
        if not check.rollback_safe:
            lay.addWidget(self._warn("Bu güncelleme veritabanı yapısını geri dönüşsüz değiştirir. Sorun olursa "
                                     "önceki sürüme dönmek için güncelleme öncesi alınan yedek kullanılmalıdır."))
        if not service.can_install:
            lay.addWidget(self._warn("Bu kurulum otomatik güncellemeyi desteklemiyor (geliştirme modu). "
                                     "Yeni sürümü GitHub sayfasından indirebilirsiniz."))
        self.status = label("", "Muted", wrap=True)
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        self.close_btn = button("Daha sonra")
        self.close_btn.clicked.connect(self._close)
        self.go_btn = button("İndir ve hazırla", "Primary")
        self.go_btn.setEnabled(service.can_install)
        self.go_btn.clicked.connect(self._start)
        self.restart_btn = button("Yeniden başlat ve güncelle", "Primary")
        self.restart_btn.hide()
        self.restart_btn.clicked.connect(self._restart)
        row.addWidget(self.close_btn)
        row.addStretch(1)
        row.addWidget(self.go_btn)
        row.addWidget(self.restart_btn)
        lay.addLayout(row)

    @staticmethod
    def _warn(text):
        w = label(text, wrap=True)
        w.setStyleSheet(f"color: {theme.WARNING};")
        return w

    def _start(self):
        if self.check.previously_failed and not confirm(self, "Tekrar dene",
                                                        "Bu sürüm daha önce başarısız oldu. Yine de denensin mi?"):
            return
        if not self.check.rollback_safe and not confirm(self, "Geri dönüşsüz güncelleme",
                                                        "Bu güncelleme sonrasında önceki sürüm veritabanını açamayabilir. "
                                                        "Devam edilsin mi?", "Devam et", danger=True):
            return
        self._busy = True
        self.go_btn.setEnabled(False)
        self.close_btn.setText("İptal")
        self.progress.show()
        self.progress.setRange(0, 0)

        def job(emit):
            return self.service.prepare(self.check, lambda st, d, t: emit((st, d, t)), self._cancel.is_set)
        run_async(job, self._done, self._failed, owner=self, on_progress=self._on_progress)

    def _on_progress(self, value):
        stage, done, total = value
        self.status.setText(STAGES.get(stage, stage))
        if stage == "download" and total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
            self.status.setText(f"İndiriliyor… {done / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.progress.setRange(0, 0)

    def _done(self, version):
        self._busy = False
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status.setText(f"{version} doğrulandı ve hazırlandı. Uygulama yeniden başlatıldığında yeni sürüm "
                            "açılacak; açılamazsa mevcut sürüme otomatik dönülecek.")
        self.close_btn.setText("Daha sonra")
        self.go_btn.hide()
        self.restart_btn.show()

    def _failed(self, exc):
        self._busy = False
        self.progress.hide()
        self.close_btn.setText("Kapat")
        self.go_btn.setEnabled(self.service.can_install)
        self.status.setStyleSheet(f"color: {theme.DANGER};")
        self.status.setText(f"Güncelleme hazırlanamadı: {exc}\nMevcut kurulum değiştirilmedi.")

    def _close(self):
        if self._busy:
            self._cancel.set()
            self.status.setText("İptal ediliyor…")
            return
        self.reject()

    def closeEvent(self, event):
        if self._busy:
            self._cancel.set()
            event.ignore()
            return
        super().closeEvent(event)

    def _restart(self):
        self.restart_btn.setEnabled(False)
        self.on_restart()
