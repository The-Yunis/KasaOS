"""Ayarlar — general, payment methods & accounts, backups, updates."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from kasaos.core.exceptions import ValidationError
from kasaos.domain.enums import AccountKind
from kasaos.domain.money import format_amount, parse_amount
from kasaos.ui import theme
from kasaos.ui.components import Card, PageHeader, button, configure_table, confirm, label, show_error
from kasaos.ui.pages.base import Page
from kasaos.ui.workers import run_async
from kasaos.version import SCHEMA_VERSION


def open_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    configure_table(t)
    t.horizontalHeader().setStretchLastSection(True)
    t.setMinimumHeight(200)
    return t


class NameDialog(QDialog):
    """Small form used for payment methods and accounts."""

    def __init__(self, parent, title, name="", accounts=None, account_id=None, opening=None, active=None,
                 kinds=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(60)
        form.addRow("Ad", self.name)
        self.account = QComboBox()
        if accounts is not None:
            for a in accounts:
                self.account.addItem(a.name, a.id)
            self.account.setCurrentIndex(max(0, self.account.findData(account_id)))
            form.addRow("Bağlı hesap", self.account)
        self.kind = QComboBox()
        if kinds:
            for k in AccountKind:
                self.kind.addItem(k.label, k.value)
            form.addRow("Tür", self.kind)
        self.opening = QLineEdit()
        if opening is not None:
            self.opening.setText(format_amount(opening, symbol=False))
            form.addRow("Açılış bakiyesi", self.opening)
        self.active = QCheckBox("Aktif")
        if active is not None:
            self.active.setChecked(active)
            form.addRow("", self.active)
        lay.addLayout(form)
        self.err = label("", "ErrorText", wrap=True)
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        c = button("Vazgeç")
        c.clicked.connect(self.reject)
        ok = button("Kaydet", "Primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        row.addWidget(c)
        row.addWidget(ok)
        lay.addLayout(row)
        self.opening_value = opening or 0

    def _ok(self):
        if not self.name.text().strip():
            self.err.setText("Ad boş olamaz.")
            return
        if self.opening.isVisibleTo(self) and self.opening.text().strip() not in ("", "0", "0,00"):
            try:
                self.opening_value = parse_amount(self.opening.text())
            except ValidationError as e:
                self.err.setText(str(e))
                return
        elif self.opening.isVisibleTo(self):
            self.opening_value = 0
        self.accept()


class SettingsPage(Page):
    title = "Ayarlar"

    def __init__(self, window):
        super().__init__(window)
        self.content.addWidget(PageHeader("Ayarlar", "İşletme, ödeme yöntemleri, yedekleme ve güncellemeler"))
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "Genel")
        tabs.addTab(self._methods_tab(), "Ödeme Yöntemleri ve Hesaplar")
        tabs.addTab(self._backup_tab(), "Yedekleme")
        tabs.addTab(self._update_tab(), "Güncelleme")
        self.content.addWidget(tabs, 1)
        footer = label(f"KasaOS · {window.version_text}  ·  Coded by Yunus Açıkgöz", "Faint")
        self.content.addWidget(footer)

    # --- tabs -----------------------------------------------------------------------
    def _general_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        card = Card()
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.business = QLineEdit()
        self.business.setMaxLength(80)
        self.business.setPlaceholderText("İşletmenizin adı")
        form.addRow("İşletme adı", self.business)
        self.def_income = QComboBox()
        self.def_expense = QComboBox()
        form.addRow("Varsayılan gelir ödeme yöntemi", self.def_income)
        form.addRow("Varsayılan gider ödeme yöntemi", self.def_expense)
        card.body.addLayout(form)
        save = button("Kaydet", "Primary")
        save.clicked.connect(self._save_general)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(save)
        card.body.addLayout(row)
        lay.addWidget(card)
        paths = Card()
        paths.body.addWidget(label("Veri konumları", "SectionTitle"))
        p = self.ctx.paths
        paths.body.addWidget(label(f"Veritabanı: {p.database}<br>Yedekler: {p.backups_dir}<br>"
                                   f"Günlükler: {p.logs_dir}", "Muted", wrap=True))
        r = QHBoxLayout()
        for text, path in (("Veri klasörü", p.data_dir), ("Günlük klasörü", p.logs_dir)):
            b = button(text, icon="folder")
            b.clicked.connect(lambda _=False, x=path: open_folder(x))
            r.addWidget(b)
        r.addStretch(1)
        paths.body.addLayout(r)
        lay.addWidget(paths)
        lay.addStretch(1)
        return w

    def _methods_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        mc = Card()
        mc.body.addWidget(label("Ödeme yöntemleri", "SectionTitle"))
        mc.body.addWidget(label("Her ödeme yöntemi bir hesaba bağlıdır; örneğin “Nakit” girişleri nakit kasaya, "
                                "“Kredi kartı” girişleri POS hesabına işlenir.", "Faint", wrap=True))
        self.methods_table = _table(["Ad", "Bağlı hesap", "Durum"])
        mc.body.addWidget(self.methods_table)
        r = QHBoxLayout()
        b1 = button("Yöntem ekle", icon="plus")
        b1.clicked.connect(self._add_method)
        b2 = button("Düzenle", icon="edit")
        b2.clicked.connect(self._edit_method)
        r.addWidget(b1)
        r.addWidget(b2)
        r.addStretch(1)
        mc.body.addLayout(r)
        lay.addWidget(mc)
        ac = Card()
        ac.body.addWidget(label("Hesaplar", "SectionTitle"))
        ac.body.addWidget(label("Açılış bakiyesi, KasaOS'u kullanmaya başladığınız andaki hesap bakiyesidir.",
                                "Faint", wrap=True))
        self.accounts_table = _table(["Ad", "Tür", "Açılış bakiyesi", "Durum"])
        ac.body.addWidget(self.accounts_table)
        r = QHBoxLayout()
        b3 = button("Hesap ekle", icon="plus")
        b3.clicked.connect(self._add_account)
        b4 = button("Düzenle", icon="edit")
        b4.clicked.connect(self._edit_account)
        r.addWidget(b3)
        r.addWidget(b4)
        r.addStretch(1)
        ac.body.addLayout(r)
        lay.addWidget(ac)
        return w

    def _backup_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        card = Card()
        card.body.addWidget(label("Veritabanı yedekleri", "SectionTitle"))
        card.body.addWidget(label("Yedekler doğrulanarak oluşturulur. Geri yükleme öncesinde mevcut veriniz "
                                  "otomatik olarak ayrıca yedeklenir.", "Faint", wrap=True))
        self.auto_backup = QCheckBox("Her açılışta otomatik yedek al (son 30 otomatik yedek saklanır)")
        self.auto_backup.toggled.connect(lambda v: self._set("auto_backup_on_start", v))
        card.body.addWidget(self.auto_backup)
        self.backup_table = _table(["Tarih", "Tür", "Boyut", "Şema"])
        card.body.addWidget(self.backup_table)
        r = QHBoxLayout()
        self.backup_btn = button("Şimdi yedekle", "Primary", icon="backup", icon_color="#17150F")
        self.backup_btn.clicked.connect(self._backup_now)
        self.export_btn = button("Yedeği dışa aktar…", icon="download")
        self.export_btn.clicked.connect(self._export_backup)
        restore = button("Seçili yedeği geri yükle", "Danger")
        restore.clicked.connect(lambda: self._restore(self._selected_backup()))
        restore_file = button("Dosyadan geri yükle…")
        restore_file.clicked.connect(self._restore_file)
        folder = button("Yedek klasörü", icon="folder")
        folder.clicked.connect(lambda: open_folder(self.ctx.paths.backups_dir))
        for b in (self.backup_btn, self.export_btn, restore, restore_file):
            r.addWidget(b)
        r.addStretch(1)
        r.addWidget(folder)
        card.body.addLayout(r)
        lay.addWidget(card)
        lay.addStretch(1)
        return w

    def _update_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        card = Card()
        card.body.addWidget(label("Güncellemeler", "SectionTitle"))
        card.body.addWidget(label(
            "Güncellemeler GitHub Releases üzerinden alınır, imzası ve SHA-256 özeti doğrulanır, ayrı bir klasöre "
            "hazırlanır. Yeni sürüm başarıyla açılmazsa önceki sürüme otomatik dönülür; verileriniz etkilenmez.",
            "Faint", wrap=True))
        form = QFormLayout()
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("GitHub kullanıcı / kurum adı")
        self.repo = QLineEdit()
        form.addRow("Depo sahibi", self.owner)
        form.addRow("Depo adı", self.repo)
        card.body.addLayout(form)
        self.check_start = QCheckBox("Açılışta güncellemeleri denetle (arka planda)")
        self.prerelease = QCheckBox("Ön sürümleri (beta) de göster")
        card.body.addWidget(self.check_start)
        card.body.addWidget(self.prerelease)
        r = QHBoxLayout()
        save = button("Kaydet")
        save.clicked.connect(lambda: self._save_update())
        check = button("Şimdi denetle", "Primary", icon="refresh", icon_color="#17150F")
        check.clicked.connect(lambda: self._save_update(then=lambda: self.window_.check_updates(interactive=True)))
        r.addWidget(save)
        r.addWidget(check)
        r.addStretch(1)
        card.body.addLayout(r)
        card.body.addWidget(label(f"Sürüm {self.window_.version_text} · Veritabanı şeması {SCHEMA_VERSION}",
                                  "Muted"))
        lay.addWidget(card)
        lay.addStretch(1)
        return w

    # --- data -------------------------------------------------------------------------
    def load(self, _):
        s = self.ctx.settings
        return {
            "settings": {k: s.get(k) for k in ("business_name", "update_owner", "update_repo",
                                               "update_check_on_start", "update_allow_prerelease",
                                               "auto_backup_on_start", "default_income_method",
                                               "default_expense_method")},
            "methods": self.ctx.catalog.payment_methods(include_inactive=True),
            "accounts": self.ctx.catalog.accounts(include_inactive=True),
            "backups": self.ctx.backups.list(),
        }

    def apply(self, d):
        s = d["settings"]
        self._methods, self._accounts, self._backups = d["methods"], d["accounts"], d["backups"]
        self.business.setText(s["business_name"])
        acc_names = {a.id: a.name for a in self._accounts}
        for combo, key in ((self.def_income, "default_income_method"), (self.def_expense, "default_expense_method")):
            combo.clear()
            combo.addItem("İlk yöntem", "")
            for m in self._methods:
                if m.active:
                    combo.addItem(m.name, str(m.id))
            combo.setCurrentIndex(max(0, combo.findData(s[key])))
        self.methods_table.setRowCount(0)
        for m in self._methods:
            self._row(self.methods_table, [m.name, acc_names.get(m.account_id, "?"), "Aktif" if m.active else "Pasif"])
        self.accounts_table.setRowCount(0)
        for a in self._accounts:
            self._row(self.accounts_table, [a.name, a.kind.label, format_amount(a.opening_balance),
                                            "Aktif" if a.active else "Pasif"])
        self.backup_table.setRowCount(0)
        for b in self._backups:
            self._row(self.backup_table, [b.created.strftime("%d.%m.%Y %H:%M:%S"), _reason(b.reason),
                                          f"{b.size / 1024:.0f} KB", str(b.schema_version) if b.schema_version >= 0
                                          else "Okunamadı"])
        for cb, key in ((self.auto_backup, "auto_backup_on_start"), (self.check_start, "update_check_on_start"),
                        (self.prerelease, "update_allow_prerelease")):
            cb.blockSignals(True)
            cb.setChecked(s[key] == "1")
            cb.blockSignals(False)
        self.owner.setText(s["update_owner"])
        self.repo.setText(s["update_repo"])

    @staticmethod
    def _row(table, values):
        r = table.rowCount()
        table.insertRow(r)
        for c, v in enumerate(values):
            table.setItem(r, c, QTableWidgetItem(v))

    def _run(self, fn, ok_msg, title, refresh_all=False):
        def done(_):
            self.window_.notify(ok_msg)
            if refresh_all:
                self.window_.data_changed()
            else:
                self.refresh()
        run_async(fn, done, lambda e: show_error(self, title, e), owner=self)

    def _set(self, key, value):
        self._run(lambda: self.ctx.settings.set(key, value), "Ayar kaydedildi.", "Ayar kaydedilemedi")

    def _save_general(self):
        values = {"business_name": self.business.text().strip(),
                  "default_income_method": self.def_income.currentData() or "",
                  "default_expense_method": self.def_expense.currentData() or ""}
        self._run(lambda: self.ctx.settings.set_many(values), "Ayarlar kaydedildi.", "Kaydedilemedi", True)

    def _save_update(self, then=None):
        values = {"update_owner": self.owner.text().strip(), "update_repo": self.repo.text().strip(),
                  "update_check_on_start": self.check_start.isChecked(),
                  "update_allow_prerelease": self.prerelease.isChecked()}

        def done(_):
            if then:
                then()
            else:
                self.window_.notify("Güncelleme ayarları kaydedildi.")
        run_async(lambda: self.ctx.settings.set_many(values), done,
                  lambda e: show_error(self, "Kaydedilemedi", e), owner=self)

    # payment methods / accounts
    def _sel(self, table, items):
        r = table.currentRow()
        return items[r] if 0 <= r < len(items) else None

    def _add_method(self):
        dlg = NameDialog(self, "Yeni ödeme yöntemi", accounts=[a for a in self._accounts if a.active])
        if dlg.exec():
            name, acc = dlg.name.text(), dlg.account.currentData()
            self._run(lambda: self.ctx.catalog.add_payment_method(name, acc), "Ödeme yöntemi eklendi.",
                      "Eklenemedi", True)

    def _edit_method(self):
        m = self._sel(self.methods_table, self._methods)
        if not m:
            return
        dlg = NameDialog(self, "Ödeme yöntemini düzenle", m.name, self._accounts, m.account_id, active=m.active)
        if dlg.exec():
            name, acc, active = dlg.name.text(), dlg.account.currentData(), dlg.active.isChecked()
            self._run(lambda: self.ctx.catalog.update_payment_method(m.id, name, acc, active),
                      "Ödeme yöntemi güncellendi.", "Güncellenemedi", True)

    def _add_account(self):
        dlg = NameDialog(self, "Yeni hesap", opening=0, kinds=True)
        if dlg.exec():
            name, kind, opening = dlg.name.text(), AccountKind(dlg.kind.currentData()), dlg.opening_value
            self._run(lambda: self.ctx.catalog.add_account(name, kind, opening), "Hesap eklendi.", "Eklenemedi", True)

    def _edit_account(self):
        a = self._sel(self.accounts_table, self._accounts)
        if not a:
            return
        dlg = NameDialog(self, "Hesabı düzenle", a.name, opening=a.opening_balance, active=a.active)
        if dlg.exec():
            name, opening, active = dlg.name.text(), dlg.opening_value, dlg.active.isChecked()
            self._run(lambda: self.ctx.catalog.update_account(a.id, name, opening, active), "Hesap güncellendi.",
                      "Güncellenemedi", True)

    # backups
    def _selected_backup(self):
        b = self._sel(self.backup_table, getattr(self, "_backups", []))
        return b.path if b else None

    def _backup_now(self):
        self.backup_btn.setEnabled(False)

        def done(path):
            self.backup_btn.setEnabled(True)
            self.window_.notify("Yedek oluşturuldu ve doğrulandı.")
            self.refresh()
        run_async(lambda: self.ctx.backups.create("manual"), done,
                  lambda e: (self.backup_btn.setEnabled(True), show_error(self, "Yedeklenemedi", e)), owner=self)

    def _export_backup(self):
        from datetime import datetime
        from pathlib import Path
        name = f"KasaOS-yedek-{datetime.now():%Y%m%d-%H%M}.kasaosbak"
        path, _ = QFileDialog.getSaveFileName(self, "Yedeği kaydet", name, "KasaOS yedeği (*.kasaosbak)")
        if path:
            self._run(lambda: self.ctx.backups.create("export", Path(path)), "Yedek dışa aktarıldı.",
                      "Dışa aktarılamadı")

    def _restore_file(self):
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(self, "Yedek dosyası seç", str(self.ctx.paths.backups_dir),
                                              "KasaOS yedeği (*.kasaosbak *.db);;Tüm dosyalar (*)")
        if path:
            self._restore(Path(path))

    def _restore(self, path):
        if path is None:
            show_error(self, "Geri yükleme", "Önce listeden bir yedek seçin.")
            return
        if not confirm(self, "Yedeği geri yükle",
                       f"{path.name} geri yüklenecek.\n\nBu yedekten sonra girilen kayıtlar geçerli veritabanından "
                       f"kalkacaktır. Mevcut veritabanı önce ayrıca yedeklenir, böylece gerekirse geri dönebilirsiniz."
                       f"\n\nDevam edilsin mi?", "Geri yükle", danger=True):
            return

        def job():
            safety = self.ctx.backups.restore(path, SCHEMA_VERSION)
            self.ctx.open_database()
            return safety

        def done(safety):
            self.window_.data_changed()
            self.window_.notify("Yedek geri yüklendi. Önceki veri yedeği: " + safety.name)

        def fail(e):
            if not self.ctx.db.is_open:
                try:
                    self.ctx.open_database()
                except Exception as reopen_error:  # reported, not hidden
                    show_error(self, "Veritabanı yeniden açılamadı", reopen_error)
            show_error(self, "Geri yükleme başarısız", e)
        run_async(job, done, fail, owner=self)


def _reason(r: str) -> str:
    if r.startswith("pre-migration"):
        return "Şema güncellemesi öncesi"
    if r.startswith("pre-update"):
        return "Uygulama güncellemesi öncesi"
    return {"auto": "Otomatik", "manual": "Elle", "pre-restore": "Geri yükleme öncesi",
            "export": "Dışa aktarım"}.get(r, r or "—")
