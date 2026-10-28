"""Fast entry / edit form for every transaction kind.

Keyboard flow: amount → category → payment method → description → Enter.
Enter saves only after service-side validation passes; on failure the values
stay in place and the offending field is highlighted. While a save is in
flight both save buttons are disabled (no duplicate submissions).
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QTime, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QTimeEdit, QVBoxLayout)

from kasaos.core.application_context import AppContext
from kasaos.core.exceptions import KasaOSError, ValidationError
from kasaos.domain.entities import Transaction, TransactionDraft
from kasaos.domain.enums import TxKind
from kasaos.domain.money import format_amount, parse_amount
from kasaos.ui import theme
from kasaos.ui.components import button, label
from kasaos.ui.reference import ReferenceData
from kasaos.ui.workers import run_async

TITLES = {
    TxKind.INCOME: "Gelir Ekle", TxKind.EXPENSE: "Gider Ekle", TxKind.TRANSFER: "Hesaplar Arası Transfer",
    TxKind.OWNER_WITHDRAWAL: "Sahip Çekişi", TxKind.OWNER_DEPOSIT: "Sermaye Girişi",
}
HINTS = {
    TxKind.TRANSFER: "Transferler gelir veya gider sayılmaz; yalnızca hesap bakiyelerini değiştirir.",
    TxKind.OWNER_WITHDRAWAL: "İşletmeden kişisel kullanım için alınan para. İşletme gideri olarak sayılmaz.",
    TxKind.OWNER_DEPOSIT: "İşletmeye konulan sermaye. Gelir olarak sayılmaz.",
}


class TransactionDialog(QDialog):
    saved = Signal(object)  # Transaction

    def __init__(self, ctx: AppContext, ref: ReferenceData, kind: TxKind, parent=None,
                 existing: Transaction | None = None):
        super().__init__(parent)
        self.ctx, self.ref, self.kind, self.existing = ctx, ref, kind, existing
        self._busy = False
        self._keep_open = False
        self.setWindowTitle(("İşlemi Düzenle — " if existing else "") + TITLES[kind])
        self.setMinimumWidth(560)
        self._build()
        if existing:
            self._load(existing)
        self.amount.setFocus()

    # -- layout -----------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        color = {TxKind.INCOME: theme.INCOME, TxKind.EXPENSE: theme.EXPENSE}.get(self.kind, theme.GOLD_SOFT)
        title = label(self.windowTitle(), "SectionTitle")
        title.setStyleSheet(f"color: {color}; font-size: 13pt;")
        root.addWidget(title)
        if self.kind in HINTS:
            root.addWidget(label(HINTS[self.kind], "Muted", wrap=True))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.amount = QLineEdit()
        self.amount.setObjectName("AmountEdit")
        self.amount.setPlaceholderText("0,00")
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.amount.textChanged.connect(lambda: self._mark(self.amount, False))
        self.amount.editingFinished.connect(self._normalise_amount)
        amount_row = QHBoxLayout()
        amount_row.addWidget(self.amount, 1)
        amount_row.addWidget(label("₺", "SectionTitle"))
        form.addRow("Tutar", amount_row)

        self.category = QComboBox()
        self.method = QComboBox()
        self.account = QComboBox()
        self.to_account = QComboBox()
        self.refund = QCheckBox("İade / düzeltme kaydı (tutarı ters yönde işler)")

        if self.kind in (TxKind.INCOME, TxKind.EXPENSE):
            cats = self.ref.income_categories if self.kind == TxKind.INCOME else self.ref.expense_categories
            self.category.addItem("Kategori seçin…", None)
            for c in cats:
                self.category.addItem(c.name, c.id)
            if len(cats) == 1:
                self.category.setCurrentIndex(1)
            form.addRow("Kategori", self.category)
            for m in self.ref.methods:
                self.method.addItem(m.name, m.id)
            default = (self.ref.default_income_method if self.kind == TxKind.INCOME
                       else self.ref.default_expense_method)
            idx = self.method.findData(default) if default else 0
            self.method.setCurrentIndex(max(idx, 0))
            form.addRow("Ödeme yöntemi", self.method)
        else:
            for a in self.ref.accounts:
                self.account.addItem(a.name, a.id)
            form.addRow("Kaynak hesap" if self.kind == TxKind.TRANSFER else "Hesap", self.account)
            if self.kind == TxKind.TRANSFER:
                for a in self.ref.accounts:
                    self.to_account.addItem(a.name, a.id)
                if self.to_account.count() > 1:
                    self.to_account.setCurrentIndex(1)
                form.addRow("Hedef hesap", self.to_account)

        date_row = QHBoxLayout()
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy")
        self.time = QTimeEdit(QTime.currentTime())
        self.time.setDisplayFormat("HH:mm")
        self.time.setMinimumWidth(80)
        self.date.setMinimumWidth(130)
        today_btn = button("Bugün", "Ghost")
        yday_btn = button("Dün", "Ghost")
        today_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        yday_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        today_btn.clicked.connect(lambda: self.date.setDate(QDate.currentDate()))
        yday_btn.clicked.connect(lambda: self.date.setDate(QDate.currentDate().addDays(-1)))
        date_row.addWidget(self.date, 1)
        date_row.addWidget(self.time)
        date_row.addWidget(today_btn)
        date_row.addWidget(yday_btn)
        form.addRow("Tarih", date_row)

        self.description = QLineEdit()
        self.description.setPlaceholderText("ör. Akşam satışları, tedarikçi adı…")
        self.description.setMaxLength(500)
        form.addRow("Açıklama", self.description)
        self.note = QLineEdit()
        self.note.setPlaceholderText("İsteğe bağlı not")
        self.note.setMaxLength(500)
        form.addRow("Not", self.note)
        if self.kind in (TxKind.INCOME, TxKind.EXPENSE):
            form.addRow("", self.refund)
        root.addLayout(form)

        self.error = label("", "ErrorText", wrap=True)
        self.error.hide()
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        self.cancel_btn = button("Vazgeç")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_new_btn = button("Kaydet ve Yeni")
        self.save_new_btn.setAutoDefault(False)
        self.save_new_btn.setToolTip("Ctrl+Enter")
        self.save_new_btn.clicked.connect(lambda: self._submit(keep_open=True))
        self.save_btn = button("Kaydet", "Primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(lambda: self._submit(keep_open=False))
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        if not self.existing:
            buttons.addWidget(self.save_new_btn)
        buttons.addWidget(self.save_btn)
        root.addLayout(buttons)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=lambda: self._submit(keep_open=not self.existing))
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=lambda: self._submit(keep_open=not self.existing))

        # Enter in the amount field moves on instead of submitting a half-filled form.
        self.amount.returnPressed.connect(self._advance_from_amount)

        self.setTabOrder(self.amount, self.category if self.kind in (TxKind.INCOME, TxKind.EXPENSE) else self.account)

    def _advance_from_amount(self):
        if self.kind in (TxKind.INCOME, TxKind.EXPENSE) and self.category.currentData() is None:
            self.category.setFocus()
            self.category.showPopup()
        else:
            self.description.setFocus()

    def keyPressEvent(self, event):
        # QDialog would trigger the default button on Enter from any field; route it
        # through _submit only (validation first), and ignore it while busy.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            if self.focusWidget() is self.amount:
                return
            self._submit(keep_open=False)
            return
        super().keyPressEvent(event)

    def _load(self, t: Transaction):
        self.amount.setText(format_amount(t.amount, symbol=False))
        if t.category_id is not None:
            idx = self.category.findData(t.category_id)
            if idx < 0:  # archived category: keep it selectable for this record
                cat = next((c for c in self.ref.all_categories if c.id == t.category_id), None)
                self.category.addItem((cat.name if cat else "?") + " (pasif)", t.category_id)
                idx = self.category.count() - 1
            self.category.setCurrentIndex(idx)
        if t.payment_method_id is not None:
            idx = self.method.findData(t.payment_method_id)
            if idx >= 0:
                self.method.setCurrentIndex(idx)
        if self.account.count():
            self.account.setCurrentIndex(max(0, self.account.findData(t.account_id)))
        if t.to_account_id is not None:
            self.to_account.setCurrentIndex(max(0, self.to_account.findData(t.to_account_id)))
        self.date.setDate(QDate(t.occurred_on.year, t.occurred_on.month, t.occurred_on.day))
        if t.occurred_time:
            self.time.setTime(QTime.fromString(t.occurred_time, "HH:mm"))
        self.description.setText(t.description)
        self.note.setText(t.note)
        self.refund.setChecked(t.is_refund)

    # -- behaviour ----------------------------------------------------------------------
    def _normalise_amount(self):
        try:
            self.amount.setText(format_amount(parse_amount(self.amount.text()), symbol=False))
        except ValidationError:
            pass  # reported on submit; keep what the user typed

    def _mark(self, widget, invalid: bool):
        widget.setProperty("invalid", invalid)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _show_error(self, text: str, field: str | None):
        self.error.setText(text)
        self.error.show()
        target = {"amount": self.amount, "category": self.category, "payment_method": self.method,
                  "account": self.account, "to_account": self.to_account, "date": self.date,
                  "description": self.description}.get(field or "")
        if target is not None:
            if hasattr(target, "setProperty"):
                self._mark(target, True)
            target.setFocus()

    def _draft(self) -> TransactionDraft:
        amount = parse_amount(self.amount.text())
        qd = self.date.date()
        kind = self.kind
        d = TransactionDraft(kind=kind, occurred_on=date(qd.year(), qd.month(), qd.day()), amount=amount,
                             description=self.description.text(), note=self.note.text(),
                             occurred_time=self.time.time().toString("HH:mm"))
        if kind in (TxKind.INCOME, TxKind.EXPENSE):
            d.category_id = self.category.currentData()
            d.payment_method_id = self.method.currentData()
            d.is_refund = self.refund.isChecked()
        else:
            d.account_id = self.account.currentData()
            if kind == TxKind.TRANSFER:
                d.to_account_id = self.to_account.currentData()
        return d

    def _submit(self, keep_open: bool):
        if self._busy:
            return
        self.error.hide()
        for w in (self.amount, self.category, self.method):
            self._mark(w, False)
        try:
            draft = self._draft()
        except ValidationError as e:
            self._show_error(str(e), e.field)
            return
        self._set_busy(True)
        self._keep_open = keep_open
        svc = self.ctx.transactions
        if self.existing:
            job = lambda: svc.update(self.existing.id, draft)  # noqa: E731
        else:
            job = lambda: svc.create(draft)  # noqa: E731
        run_async(job, self._on_saved, self._on_failed, owner=self)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.save_btn.setEnabled(not busy)
        self.save_new_btn.setEnabled(not busy)
        self.save_btn.setText("Kaydediliyor…" if busy else "Kaydet")

    def _on_saved(self, tx: Transaction):
        self._set_busy(False)
        self.saved.emit(tx)  # emitted only after the DB transaction committed
        if self._keep_open:
            self.amount.clear()
            self.description.clear()
            self.note.clear()
            self.refund.setChecked(False)
            self.amount.setFocus()
            self.error.setStyleSheet(f"color: {theme.INCOME};")
            self.error.setText(f"Kaydedildi: {format_amount(tx.amount)} — sıradaki işlemi girebilirsiniz.")
            self.error.show()
        else:
            self.accept()

    def _on_failed(self, exc: Exception):
        self._set_busy(False)
        self.error.setStyleSheet("")
        if isinstance(exc, ValidationError):
            self._show_error(str(exc), exc.field)
        elif isinstance(exc, KasaOSError):
            self._show_error(str(exc), None)
        else:
            self._show_error("Kayıt sırasında beklenmeyen bir hata oluştu; işlem kaydedilmedi. "
                             "Ayrıntılar günlük dosyasında.", None)
