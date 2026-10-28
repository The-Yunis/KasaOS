"""Gelir İşlemleri / Gider İşlemleri / İşlem Geçmişi — one filterable list page."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QHBoxLayout, QLineEdit, QListWidget, QStackedWidget,
                               QTableView, QVBoxLayout)

from kasaos.domain.entities import TransactionFilter
from kasaos.domain.enums import TxKind
from kasaos.domain.financial_rules import signed_expense, signed_income
from kasaos.domain.money import format_amount
from kasaos.ui import theme
from kasaos.ui.components import (Card, EmptyState, PageHeader, TransactionModel, button, configure_table, confirm,
                                  label, show_error)
from kasaos.ui.pages.base import Page
from kasaos.ui.workers import run_async

PRESETS = ["Bugün", "Dün", "Bu hafta", "Bu ay", "Geçen ay", "Son 30 gün", "Bu yıl", "Tümü", "Özel aralık"]


def preset_range(name: str) -> tuple[date | None, date | None]:
    t = date.today()
    if name == "Bugün":
        return t, t
    if name == "Dün":
        y = t - timedelta(days=1)
        return y, y
    if name == "Bu hafta":
        return t - timedelta(days=t.weekday()), t
    if name == "Bu ay":
        return t.replace(day=1), t
    if name == "Geçen ay":
        end = t.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if name == "Son 30 gün":
        return t - timedelta(days=29), t
    if name == "Bu yıl":
        return t.replace(month=1, day=1), t
    return None, None


def qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class DateRangeBar(QHBoxLayout):
    def __init__(self, on_change, default: str = "Bu ay"):
        super().__init__()
        self.on_change = on_change
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.d_from = QDateEdit()
        self.d_to = QDateEdit()
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
            d.dateChanged.connect(self._custom)
        self.addWidget(self.preset)
        self.addWidget(self.d_from)
        self.addWidget(label("–", "Muted"))
        self.addWidget(self.d_to)
        self._silent = False
        self.preset.currentTextChanged.connect(self._preset_changed)
        self.preset.setCurrentText(default)
        self._preset_changed(default)

    def _preset_changed(self, name: str):
        if name == "Özel aralık":
            return
        a, b = preset_range(name)
        self._silent = True
        if a and b:
            self.d_from.setDate(qdate(a))
            self.d_to.setDate(qdate(b))
        self.d_from.setEnabled(a is not None)
        self.d_to.setEnabled(a is not None)
        self._silent = False
        self.on_change()

    def _custom(self, _):
        if self._silent:
            return
        if self.preset.currentText() != "Özel aralık":
            self.preset.blockSignals(True)
            self.preset.setCurrentText("Özel aralık")
            self.preset.blockSignals(False)
            self.d_from.setEnabled(True)
            self.d_to.setEnabled(True)
        self.on_change()

    def range(self) -> tuple[date | None, date | None]:
        if self.preset.currentText() == "Tümü":
            return None, None
        a, b = pydate(self.d_from.date()), pydate(self.d_to.date())
        return (a, b) if a <= b else (b, a)


class TransactionsPage(Page):
    scrollable = False

    def __init__(self, window, mode: str):
        self.mode = mode  # "income" | "expense" | "history"
        super().__init__(window)
        titles = {"income": ("Gelir İşlemleri", "Satış ve diğer gelir kayıtları"),
                  "expense": ("Gider İşlemleri", "İşletme giderleri"),
                  "history": ("İşlem Geçmişi", "Tüm hareketler: gelir, gider, transfer ve sahip işlemleri")}
        header = PageHeader(*titles[mode])
        if mode in ("income", "history"):
            b = button("+ Gelir Ekle", "Income")
            b.clicked.connect(lambda: window.open_transaction_dialog(TxKind.INCOME))
            header.actions.addWidget(b)
        if mode in ("expense", "history"):
            b = button("+ Gider Ekle", "Expense")
            b.clicked.connect(lambda: window.open_transaction_dialog(TxKind.EXPENSE))
            header.actions.addWidget(b)
        self.content.addWidget(header)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self._debounce = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self.range = DateRangeBar(self._changed, "Bugün" if mode != "history" else "Bu ay")
        filters.addLayout(self.range)
        self.kind = QComboBox()
        if mode == "history":
            self.kind.addItem("Tüm türler", None)
            for k in TxKind:
                self.kind.addItem(k.label, k.value)
            self.kind.currentIndexChanged.connect(self._changed)
            filters.addWidget(self.kind)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._changed)
        filters.addWidget(self.category)
        self.method = QComboBox()
        self.method.currentIndexChanged.connect(self._changed)
        filters.addWidget(self.method)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Açıklama / not ara…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        filters.addWidget(self.search, 1)
        self.content.addLayout(filters)

        self.stack = QStackedWidget()
        table_card = Card(padding=0)
        self.model = TransactionModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(5, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _: self._edit())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._sync_buttons())
        table_card.body.addWidget(self.table)
        self.stack.addWidget(table_card)
        add_kind = TxKind.EXPENSE if mode == "expense" else TxKind.INCOME
        self.stack.addWidget(EmptyState("Kayıt bulunamadı",
                                        "Seçili tarih aralığı ve filtrelerle eşleşen işlem yok. Filtreleri "
                                        "değiştirin veya yeni bir işlem ekleyin.",
                                        "+ " + ("Gider" if add_kind == TxKind.EXPENSE else "Gelir") + " Ekle",
                                        lambda: window.open_transaction_dialog(add_kind)))
        self.content.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.totals = label("", "Muted")
        footer.addWidget(self.totals, 1)
        self.audit_btn = button("Değişiklik geçmişi", icon="history")
        self.audit_btn.clicked.connect(self._audit)
        self.edit_btn = button("Düzenle", icon="edit")
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn = button("Sil", "Danger", icon="trash", icon_color=theme.DANGER)
        self.del_btn.clicked.connect(self._delete)
        for b in (self.audit_btn, self.edit_btn, self.del_btn):
            footer.addWidget(b)
        self.content.addLayout(footer)
        self._ref_loaded = False
        self._sync_buttons()

    # filters --------------------------------------------------------------------------
    def set_reference(self, ref):
        cur_c, cur_m = self.category.currentData(), self.method.currentData()
        self.category.blockSignals(True)
        self.method.blockSignals(True)
        self.category.clear()
        self.category.addItem("Tüm kategoriler", None)
        cats = {"income": ref.income_categories, "expense": ref.expense_categories}.get(
            self.mode, ref.income_categories + ref.expense_categories)
        for c in cats:
            self.category.addItem(c.name, c.id)
        self.method.clear()
        self.method.addItem("Tüm ödeme yöntemleri", None)
        for m in ref.methods:
            self.method.addItem(m.name, m.id)
        self.category.setCurrentIndex(max(0, self.category.findData(cur_c)))
        self.method.setCurrentIndex(max(0, self.method.findData(cur_m)))
        self.category.blockSignals(False)
        self.method.blockSignals(False)

    def _changed(self, *_):
        if hasattr(self, "model"):
            self.refresh()

    def params(self) -> TransactionFilter:
        a, b = self.range.range()
        kinds: tuple = ()
        if self.mode == "income":
            kinds = (TxKind.INCOME,)
        elif self.mode == "expense":
            kinds = (TxKind.EXPENSE,)
        elif self.kind.currentData():
            kinds = (TxKind(self.kind.currentData()),)
        return TransactionFilter(date_from=a, date_to=b, kinds=kinds, category_id=self.category.currentData(),
                                 payment_method_id=self.method.currentData(), text=self.search.text().strip(),
                                 limit=5000)

    def load(self, f):
        return self.ctx.transactions.list(f)

    def apply(self, rows):
        self.model.set_rows(rows)
        self.stack.setCurrentIndex(0 if rows else 1)
        inc = sum(signed_income(t.kind, t.amount, t.is_refund) for t in rows)
        exp = sum(signed_expense(t.kind, t.amount, t.is_refund) for t in rows)
        parts = [f"{len(rows)} kayıt"]
        if self.mode != "expense":
            parts.append(f'Gelir: <span style="color:{theme.INCOME}">{format_amount(inc)}</span>')
        if self.mode != "income":
            parts.append(f'Gider: <span style="color:{theme.EXPENSE}">{format_amount(exp)}</span>')
        if self.mode == "history":
            parts.append(f"Fark: {format_amount(inc - exp)}")
        if len(rows) >= 5000:
            parts.append("(ilk 5000 kayıt gösteriliyor — aralığı daraltın)")
        self.totals.setText("   ·   ".join(parts))
        self._sync_buttons()

    # actions --------------------------------------------------------------------------
    def _selected(self):
        idx = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.model.rows[idx[0].row()] if idx else None

    def _sync_buttons(self):
        has = self._selected() is not None
        for b in (self.edit_btn, self.del_btn, self.audit_btn):
            b.setEnabled(has)

    def _edit(self):
        t = self._selected()
        if t:
            self.window_.open_transaction_dialog(t.kind, t)

    def _delete(self):
        t = self._selected()
        if not t:
            return
        text = (f"{t.occurred_on.strftime('%d.%m.%Y')} tarihli {format_amount(t.amount)} tutarındaki "
                f"{t.kind.label.lower()} kaydı silinsin mi?\n\nSilinen kayıt raporlardan çıkarılır; "
                f"değişiklik geçmişinde iz olarak saklanır.")
        if not confirm(self, "İşlemi sil", text, "Sil", danger=True):
            return
        self.del_btn.setEnabled(False)
        run_async(lambda: self.ctx.transactions.delete(t.id),
                  lambda _: (self.window_.notify("İşlem silindi."), self.window_.data_changed()),
                  lambda e: (show_error(self, "Silinemedi", e), self._sync_buttons()), owner=self)

    def _audit(self):
        t = self._selected()
        if not t:
            return
        run_async(lambda: self.ctx.transactions.history(t.id), lambda ev: AuditDialog(ev, self).exec(),
                  lambda e: show_error(self, "Geçmiş yüklenemedi", e), owner=self)


ACTION_LABELS = {"create": "Oluşturuldu", "update": "Düzenlendi", "delete": "Silindi"}
FIELD_LABELS = {"amount": "Tutar", "occurred_on": "Tarih", "occurred_time": "Saat", "description": "Açıklama",
                "note": "Not", "category_id": "Kategori", "payment_method_id": "Ödeme yöntemi",
                "account_id": "Hesap", "to_account_id": "Hedef hesap", "is_refund": "İade", "kind": "Tür"}


class AuditDialog(QDialog):
    def __init__(self, events, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Değişiklik geçmişi")
        self.resize(520, 360)
        lay = QVBoxLayout(self)
        lst = QListWidget()
        from datetime import datetime
        for e in events:
            at = datetime.fromisoformat(e.at).astimezone().strftime("%d.%m.%Y %H:%M")
            line = f"{at} — {ACTION_LABELS.get(e.action, e.action)}"
            if e.action == "update":
                b, a = e.details.get("before", {}), e.details.get("after", {})
                changes = []
                for k in a:
                    if b.get(k) != a.get(k):
                        bv, av = b.get(k), a.get(k)
                        if k == "amount":
                            bv, av = format_amount(bv), format_amount(av)
                        changes.append(f"{FIELD_LABELS.get(k, k)}: {bv} → {av}")
                if changes:
                    line += "\n    " + "\n    ".join(changes)
            lst.addItem(line)
        lay.addWidget(lst)
        close = button("Kapat")
        close.clicked.connect(self.accept)
        lay.addWidget(close)
