"""Kategoriler — manage income and expense categories."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QVBoxLayout)

from kasaos.core.exceptions import ValidationError
from kasaos.domain.enums import CategoryKind
from kasaos.ui import theme
from kasaos.ui.components import Card, PageHeader, button, confirm, label, show_error
from kasaos.ui.pages.base import Page
from kasaos.ui.workers import run_async


def swatch(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


class CategoryDialog(QDialog):
    def __init__(self, parent, kind: CategoryKind, name="", color="#C9A227", active=True, editing=False):
        super().__init__(parent)
        self.setWindowTitle(("Kategoriyi düzenle" if editing else "Yeni kategori") +
                            (" — Gelir" if kind == CategoryKind.INCOME else " — Gider"))
        self.color = color
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(60)
        form.addRow("Ad", self.name)
        self.color_btn = button(color)
        self.color_btn.setIcon(swatch(color))
        self.color_btn.clicked.connect(self._pick)
        form.addRow("Renk", self.color_btn)
        self.active = QCheckBox("Aktif (işlem girişinde görünsün)")
        self.active.setChecked(active)
        if editing:
            form.addRow("", self.active)
        lay.addLayout(form)
        self.err = label("", "ErrorText", wrap=True)
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Vazgeç")
        cancel.clicked.connect(self.reject)
        ok = button("Kaydet", "Primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.name.setFocus()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Renk seç")
        if c.isValid():
            self.color = c.name().upper()
            self.color_btn.setText(self.color)
            self.color_btn.setIcon(swatch(self.color))

    def _ok(self):
        if not self.name.text().strip():
            self.err.setText("Kategori adı boş olamaz.")
            return
        self.accept()


class CategoriesPage(Page):
    title = "Kategoriler"

    def __init__(self, window):
        super().__init__(window)
        self.content.addWidget(PageHeader("Kategoriler", "Gelir ve gider kalemlerini düzenleyin. Kullanılan "
                                                         "kategoriler silinemez, pasif yapılabilir."))
        grid = QGridLayout()
        grid.setSpacing(14)
        self.lists: dict[CategoryKind, QListWidget] = {}
        for col, kind in enumerate((CategoryKind.INCOME, CategoryKind.EXPENSE)):
            card = Card()
            card.body.addWidget(label("Gelir kategorileri" if kind == CategoryKind.INCOME else "Gider kategorileri",
                                      "SectionTitle"))
            lst = QListWidget()
            lst.setMinimumHeight(360)
            lst.itemDoubleClicked.connect(lambda _it, k=kind: self._edit(k))
            self.lists[kind] = lst
            card.body.addWidget(lst)
            row = QHBoxLayout()
            add = button("Ekle", "Primary", icon="plus", icon_color="#17150F")
            add.clicked.connect(lambda _=False, k=kind: self._add(k))
            edit = button("Düzenle", icon="edit")
            edit.clicked.connect(lambda _=False, k=kind: self._edit(k))
            delete = button("Sil", "Danger", icon="trash", icon_color=theme.DANGER)
            delete.clicked.connect(lambda _=False, k=kind: self._delete(k))
            row.addWidget(add)
            row.addWidget(edit)
            row.addStretch(1)
            row.addWidget(delete)
            card.body.addLayout(row)
            grid.addWidget(card, 0, col)
        self.content.addLayout(grid)
        self.content.addStretch(1)

    def load(self, _):
        return self.ctx.catalog.categories(include_inactive=True)

    def apply(self, cats):
        for kind, lst in self.lists.items():
            lst.clear()
            for c in (c for c in cats if c.kind == kind):
                it = QListWidgetItem(swatch(c.color), c.name + ("" if c.active else "  (pasif)"))
                it.setData(Qt.ItemDataRole.UserRole, c)
                if not c.active:
                    it.setForeground(QColor(theme.TEXT_FAINT))
                lst.addItem(it)

    def _current(self, kind):
        it = self.lists[kind].currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _after(self, msg):
        self.window_.notify(msg)
        self.window_.data_changed()

    def _add(self, kind):
        dlg = CategoryDialog(self, kind)
        if dlg.exec():
            name, color = dlg.name.text(), dlg.color
            run_async(lambda: self.ctx.catalog.add_category(name, kind, color),
                      lambda _: self._after("Kategori eklendi."),
                      lambda e: show_error(self, "Kategori eklenemedi", e), owner=self)

    def _edit(self, kind):
        c = self._current(kind)
        if not c:
            return
        dlg = CategoryDialog(self, kind, c.name, c.color, c.active, editing=True)
        if dlg.exec():
            name, color, active = dlg.name.text(), dlg.color, dlg.active.isChecked()
            run_async(lambda: self.ctx.catalog.update_category(c.id, name, color, active),
                      lambda _: self._after("Kategori güncellendi."),
                      lambda e: show_error(self, "Kategori güncellenemedi", e), owner=self)

    def _delete(self, kind):
        c = self._current(kind)
        if not c or not confirm(self, "Kategoriyi sil", f"“{c.name}” kategorisi silinsin mi?", "Sil", danger=True):
            return

        def fail(e):
            if isinstance(e, ValidationError) and confirm(self, "Kategori kullanımda",
                                                          f"{e}\n\nKategori pasif hale getirilsin mi?", "Pasif yap"):
                run_async(lambda: self.ctx.catalog.update_category(c.id, c.name, c.color, False),
                          lambda _: self._after("Kategori pasif yapıldı."),
                          lambda err: show_error(self, "İşlem başarısız", err), owner=self)
            elif not isinstance(e, ValidationError):
                show_error(self, "Kategori silinemedi", e)

        run_async(lambda: self.ctx.catalog.delete_category(c.id), lambda _: self._after("Kategori silindi."),
                  fail, owner=self)
