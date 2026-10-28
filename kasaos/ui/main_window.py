"""Main window: fixed sidebar navigation + page workspace."""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from kasaos.core.application_context import AppContext
from kasaos.domain.enums import TxKind
from kasaos.services.update_service import UpdateService
from kasaos.ui import icons, theme
from kasaos.ui.components import Toast, button, label, show_error
from kasaos.ui.dialogs.transaction_dialog import TransactionDialog
from kasaos.ui.dialogs.update_dialog import UpdateDialog
from kasaos.ui.pages.about import AboutPage
from kasaos.ui.pages.cash import CashPage
from kasaos.ui.pages.categories import CategoriesPage
from kasaos.ui.pages.dashboard import DashboardPage
from kasaos.ui.pages.personnel import PersonnelPage
from kasaos.ui.pages.reports import ReportsPage
from kasaos.ui.pages.settings import SettingsPage
from kasaos.ui.pages.transactions import TransactionsPage
from kasaos.ui.reference import ReferenceData, load_reference
from kasaos.ui.workers import run_async, wait_for_all
from kasaos.version import APP_TAGLINE, DEVELOPER_CREDIT, __version__

log = logging.getLogger(__name__)

NAV = [
    ("dashboard", "Genel Bakış", "dashboard"),
    ("income", "Gelir İşlemleri", "income"),
    ("expense", "Gider İşlemleri", "expense"),
    ("cash", "Kasa Yönetimi", "cash"),
    ("personnel", "Personel", "personnel"),
    ("history", "İşlem Geçmişi", "history"),
    ("reports", "Raporlar", "reports"),
    ("categories", "Kategoriler", "categories"),
    ("settings", "Ayarlar", "settings"),
    ("about", "Hakkında", "about"),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, updates: UpdateService, ref: ReferenceData, business_name: str = ""):
        super().__init__()
        self.ctx, self.updates, self.ref = ctx, updates, ref
        self.version_text = __version__
        self._closing = False
        self.setWindowTitle("KasaOS")
        self.setWindowIcon(icons.app_icon())
        self.resize(1320, 840)
        self.setMinimumSize(1060, 680)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar(business_name))
        self.stack = QStackedWidget()
        self.stack.setObjectName("Workspace")
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.toast = Toast(self.stack)

        self.pages = {
            "dashboard": DashboardPage(self), "income": TransactionsPage(self, "income"),
            "expense": TransactionsPage(self, "expense"), "cash": CashPage(self),
            "personnel": PersonnelPage(self),
            "history": TransactionsPage(self, "history"), "reports": ReportsPage(self),
            "categories": CategoriesPage(self), "settings": SettingsPage(self), "about": AboutPage(self),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        self._push_reference()
        self.navigate("dashboard")

        QShortcut(QKeySequence("Ctrl+G"), self, activated=lambda: self.open_transaction_dialog(TxKind.INCOME))
        QShortcut(QKeySequence("Ctrl+D"), self, activated=lambda: self.open_transaction_dialog(TxKind.EXPENSE))
        QShortcut(QKeySequence("F5"), self, activated=self.data_changed)

    def _sidebar(self, business_name: str) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 20, 14, 14)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icons.brand_pixmap(34, background=False))
        brand.addWidget(mark)
        word = QLabel(f'Kasa<span style="color:{theme.GOLD}">OS</span>')
        word.setObjectName("Wordmark")
        brand.addWidget(word, 1)
        lay.addLayout(brand)
        tag = label(APP_TAGLINE, "Tagline")
        tag.setContentsMargins(4, 0, 0, 0)
        lay.addWidget(tag)
        self.business_label = label(business_name, "Muted")
        self.business_label.setContentsMargins(4, 6, 0, 0)
        self.business_label.setVisible(bool(business_name))
        lay.addWidget(self.business_label)
        lay.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, ic in NAV:
            b = QPushButton("  " + text)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setIcon(icons.icon(ic, theme.TEXT_MUTED, theme.GOLD_SOFT))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            lay.addWidget(b)
            if key == "history":
                lay.addSpacing(10)
        lay.addStretch(1)
        self.update_btn = button("Güncelleme hazır", "Primary")
        self.update_btn.hide()
        self.update_btn.clicked.connect(self._open_pending_update)
        lay.addWidget(self.update_btn)
        lay.addSpacing(6)
        lay.addWidget(label(f"v{__version__}", "Credit"))
        lay.addWidget(label(DEVELOPER_CREDIT, "Credit"))
        return side

    # --- navigation / shared actions --------------------------------------------------
    def navigate(self, key: str):
        page = self.pages[key]
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(page)

    def notify(self, text: str, kind: str = "success"):
        self.toast.show_message(text, kind)

    def _push_reference(self):
        for key in ("income", "expense", "history"):
            self.pages[key].set_reference(self.ref)

    def data_changed(self):
        """Something was written: reload reference data, then mark every page stale."""
        def done(ref):
            self.ref = ref
            self._push_reference()
            for p in self.pages.values():
                p.mark_stale()
        run_async(lambda: load_reference(self.ctx), done, lambda e: show_error(self, "Yenileme hatası", e),
                  owner=self)
        run_async(lambda: self.ctx.settings.get("business_name"), self._set_business, owner=self)

    def _set_business(self, name: str):
        self.business_label.setText(name)
        self.business_label.setVisible(bool(name))

    def open_transaction_dialog(self, kind: TxKind, existing=None):
        if kind in (TxKind.INCOME, TxKind.EXPENSE):
            cats = self.ref.income_categories if kind == TxKind.INCOME else self.ref.expense_categories
            if not cats:
                show_error(self, "Kategori yok", "Önce Kategoriler sayfasından en az bir aktif kategori ekleyin.")
                return
            if not self.ref.methods:
                show_error(self, "Ödeme yöntemi yok", "Ayarlar'dan en az bir aktif ödeme yöntemi ekleyin.")
                return
        dlg = TransactionDialog(self.ctx, self.ref, kind, self, existing)
        dlg.saved.connect(lambda t: (self.notify(f"{t.kind.label} kaydedildi."), self.data_changed()))
        dlg.exec()

    # --- updates ----------------------------------------------------------------------
    def check_updates(self, interactive: bool):
        def done(result):
            self._last_check = result
            if result.status == "available":
                if result.previously_failed and not interactive:
                    log.info("Update %s available but previously failed; not prompting", result.manifest.version)
                    return
                self.update_btn.setText(f"Güncelleme: {result.manifest.version}")
                self.update_btn.show()
                if interactive:
                    self._open_pending_update()
            elif interactive:
                QMessageBox.information(self, "Güncelleme", result.message +
                                        ("\n\n" + "\n".join(result.skipped) if result.skipped else ""))
            else:
                log.info("Update check: %s %s", result.status, result.message)
        run_async(self.updates.check, done,
                  lambda e: interactive and show_error(self, "Güncelleme denetlenemedi", e), owner=self)

    def _open_pending_update(self):
        check = getattr(self, "_last_check", None)
        if check is None or check.status != "available":
            return
        UpdateDialog(self.updates, check, __version__, self._restart_for_update, self).exec()

    def _restart_for_update(self):
        try:
            self.updates.handoff()
        except Exception as e:  # report and stay running on the current version
            show_error(self, "Güncelleme başlatılamadı", e)
            return
        self.close()

    def show_update_notice(self, raw: str):
        """Result of the last launcher trial, passed via KASAOS_UPDATE_NOTICE / install state."""
        try:
            notice = json.loads(raw)
        except ValueError:
            return
        if notice.get("status") == "success":
            QMessageBox.information(self, "Güncelleme tamamlandı",
                                    f"KasaOS {notice.get('version')} sürümüne başarıyla güncellendi.")
        elif notice.get("status") == "rolled_back":
            QMessageBox.warning(self, "Güncelleme geri alındı",
                                f"KasaOS {notice.get('version')} başlatılamadı ve önceki sürüme "
                                f"({notice.get('from')}) geri dönüldü.\n\nNeden: {notice.get('reason')}\n\n"
                                "Verileriniz korunmuştur. Bu sürüm otomatik olarak tekrar kurulmayacak.")

    # --- shutdown ---------------------------------------------------------------------
    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        self._closing = True
        log.info("Shutting down: waiting for background tasks")
        if not wait_for_all(15000):
            log.warning("Background tasks still running at shutdown")
        self.ctx.shutdown()
        event.accept()
