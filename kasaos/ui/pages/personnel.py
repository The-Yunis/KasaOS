"""Personel — staff list, running balance (alacak / borç) and ledger."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QLineEdit, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from kasaos.core.exceptions import ValidationError
from kasaos.domain.entities import Employee
from kasaos.domain.enums import EmployeeEntryKind
from kasaos.domain.money import format_amount, parse_amount
from kasaos.services.employee_service import balance_sentence
from kasaos.ui import theme
from kasaos.ui.components import (Card, EmptyState, PageHeader, StatCard, button, configure_table, confirm, label,
                                  show_error)
from kasaos.ui.pages.base import Page
from kasaos.ui.workers import run_async

ENTRY_HINTS = {
    EmployeeEntryKind.ACCRUAL: "Personelin hak ettiği tutar (maaş, prim, mesai). Kasadan para çıkmaz; "
                               "işletmenin personele borcu artar.",
    EmployeeEntryKind.PAYMENT: "Personele verilen para (maaş ödemesi veya avans). Kasadan düşer ve "
                               "“Personel” gideri olarak kaydedilir.",
    EmployeeEntryKind.REPAYMENT: "Personelin işletmeye geri verdiği para. Kasaya girer ve personel giderini azaltır.",
    EmployeeEntryKind.DEDUCTION: "Personelin borcuna yazılan tutar (kırılan malzeme, alınan ürün vb.). "
                                 "Kasadan para çıkmaz.",
}
PRESETS = {
    EmployeeEntryKind.ACCRUAL: ["Aylık maaş", "Haftalık ücret", "Prim", "Fazla mesai", "Bahşiş payı"],
    EmployeeEntryKind.PAYMENT: ["Maaş ödemesi", "Avans", "Haftalık ödeme", "Prim ödemesi"],
    EmployeeEntryKind.REPAYMENT: ["Avans iadesi", "Borç ödemesi"],
    EmployeeEntryKind.DEDUCTION: ["Kırılan malzeme", "Alınan ürün", "Ceza / kesinti"],
}


def _row(table, values, colors=None):
    r = table.rowCount()
    table.insertRow(r)
    for c, v in enumerate(values):
        it = QTableWidgetItem(v)
        if colors and colors.get(c):
            it.setForeground(QColor(colors[c]))
        if c == len(values) - 1:
            it.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        table.setItem(r, c, it)


def _balance_text(b: int) -> tuple[str, str]:
    if b > 0:
        return f"Alacaklı {format_amount(b)}", theme.WARNING
    if b < 0:
        return f"Borçlu {format_amount(-b)}", theme.INFO
    return "Hesap kapalı", theme.TEXT_MUTED


class EmployeeDialog(QDialog):
    def __init__(self, parent, emp: Employee | None = None):
        super().__init__(parent)
        self.emp = emp
        self.setWindowTitle("Personeli düzenle" if emp else "Yeni personel")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(emp.name if emp else "")
        self.name.setMaxLength(80)
        self.role = QLineEdit(emp.role if emp else "")
        self.role.setPlaceholderText("ör. Garson, Nargileci, Kasiyer")
        self.phone = QLineEdit(emp.phone if emp else "")
        self.salary = QLineEdit(format_amount(emp.monthly_salary, symbol=False) if emp and emp.monthly_salary else "")
        self.salary.setPlaceholderText("İsteğe bağlı, ör. 25.000,00")
        self.note = QLineEdit(emp.note if emp else "")
        self.active = QCheckBox("Çalışıyor (aktif)")
        self.active.setChecked(emp.active if emp else True)
        form.addRow("Ad soyad", self.name)
        form.addRow("Görev", self.role)
        form.addRow("Telefon", self.phone)
        form.addRow("Aylık maaş", self.salary)
        form.addRow("Not", self.note)
        if emp:
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
        self.result_employee: Employee | None = None

    def _ok(self):
        if not self.name.text().strip():
            self.err.setText("Personel adı boş olamaz.")
            return
        salary = 0
        if self.salary.text().strip():
            try:
                salary = parse_amount(self.salary.text())
            except ValidationError as e:
                self.err.setText(str(e))
                return
        self.result_employee = Employee(self.emp.id if self.emp else 0, self.name.text(), self.role.text(),
                                        self.phone.text(), salary, self.note.text(), self.active.isChecked())
        self.accept()


class EntryDialog(QDialog):
    def __init__(self, parent, ctx, emp: Employee, kind: EmployeeEntryKind, methods):
        super().__init__(parent)
        self.ctx, self.emp, self.kind = ctx, emp, kind
        self._busy = False
        self.setWindowTitle(f"{kind.label} — {emp.name}")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        title = label(f"{kind.label} — {emp.name}", "SectionTitle")
        lay.addWidget(title)
        lay.addWidget(label(ENTRY_HINTS[kind], "Muted", wrap=True))
        form = QFormLayout()
        self.amount = QLineEdit()
        self.amount.setObjectName("AmountEdit")
        self.amount.setPlaceholderText("0,00")
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        if kind == EmployeeEntryKind.ACCRUAL and emp.monthly_salary:
            self.amount.setText(format_amount(emp.monthly_salary, symbol=False))
        if kind == EmployeeEntryKind.REPAYMENT and emp.balance < 0:
            self.amount.setText(format_amount(-emp.balance, symbol=False))
        form.addRow("Tutar (₺)", self.amount)
        self.method = QComboBox()
        for m in methods:
            self.method.addItem(m.name, m.id)
        if kind.moves_cash:
            form.addRow("Ödeme yöntemi", self.method)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd.MM.yyyy")
        form.addRow("Tarih", self.day)
        self.desc = QComboBox()
        self.desc.setEditable(True)
        self.desc.addItems(PRESETS[kind])
        self.desc.lineEdit().setMaxLength(500)
        form.addRow("Açıklama", self.desc)
        lay.addLayout(form)
        lay.addWidget(label(f"Şu anki durum: {balance_sentence(emp.name, emp.balance)}", "Faint", wrap=True))
        self.err = label("", "ErrorText", wrap=True)
        lay.addWidget(self.err)
        row = QHBoxLayout()
        cancel = button("Vazgeç")
        cancel.clicked.connect(self.reject)
        self.ok = button("Kaydet", "Primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self.amount.setFocus()
        self.amount.selectAll()

    def _save(self):
        if self._busy:
            return
        try:
            amount = parse_amount(self.amount.text())
        except ValidationError as e:
            self.err.setText(str(e))
            return
        q = self.day.date()
        day = date(q.year(), q.month(), q.day())
        method = self.method.currentData() if self.kind.moves_cash else None
        desc = self.desc.currentText()
        self._busy = True
        self.ok.setEnabled(False)
        self.ok.setText("Kaydediliyor…")
        run_async(lambda: self.ctx.employees.add_entry(self.emp.id, self.kind, amount, day, desc, method),
                  lambda _: self.accept(), self._fail, owner=self)

    def _fail(self, e):
        self._busy = False
        self.ok.setEnabled(True)
        self.ok.setText("Kaydet")
        if isinstance(e, ValidationError):
            self.err.setText(str(e))
        else:
            show_error(self, "Kaydedilemedi", e)


class PersonnelPage(Page):
    title = "Personel"

    def __init__(self, window):
        super().__init__(window)
        header = PageHeader("Personel", "Maaş, avans ve personelle olan alacak / borç takibi")
        add = button("+ Personel Ekle", "Primary")
        add.clicked.connect(self._add_employee)
        header.actions.addWidget(add)
        self.content.addWidget(header)

        cards = QGridLayout()
        cards.setSpacing(14)
        self.c_owed = StatCard("Personele toplam borcunuz", theme.WARNING, "Personelin alacaklı olduğu tutar")
        self.c_due = StatCard("Personelin size toplam borcu", theme.INFO, "Fazla avans ve kesintiler")
        self.c_count = StatCard("Aktif personel")
        for i, c in enumerate((self.c_owed, self.c_due, self.c_count)):
            cards.addWidget(c, 0, i)
        self.content.addLayout(cards)

        self.stack = QStackedWidget()
        self.stack.addWidget(EmptyState("Henüz personel yok",
                                        "Personel ekleyerek maaş, avans ve kimin ne kadar alacaklı ya da borçlu "
                                        "olduğunu takip edin.", "+ Personel Ekle", self._add_employee))
        body = QWidget()
        grid = QHBoxLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)

        left = Card()
        left.body.addWidget(label("Personel listesi", "SectionTitle"))
        self.show_inactive = QCheckBox("Ayrılanları da göster")
        self.show_inactive.toggled.connect(lambda _: self.refresh())
        left.body.addWidget(self.show_inactive)
        self.list = QTableWidget(0, 3)
        self.list.setHorizontalHeaderLabels(["Ad", "Görev", "Durum"])
        configure_table(self.list)
        self.list.horizontalHeader().setStretchLastSection(True)
        self.list.setMinimumHeight(380)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        left.body.addWidget(self.list)
        grid.addWidget(left, 2)

        right = Card()
        top = QHBoxLayout()
        self.emp_title = label("", "SectionTitle")
        self.emp_title.setStyleSheet("font-size: 14pt;")
        top.addWidget(self.emp_title, 1)
        self.edit_btn = button("Düzenle", icon="edit")
        self.edit_btn.clicked.connect(self._edit_employee)
        top.addWidget(self.edit_btn)
        right.body.addLayout(top)
        self.emp_info = label("", "Muted")
        right.body.addWidget(self.emp_info)
        self.balance_lbl = label("", wrap=True)
        self.balance_lbl.setStyleSheet("font-size: 13pt; font-weight: 600;")
        right.body.addWidget(self.balance_lbl)
        acts = QHBoxLayout()
        self.entry_buttons = []
        for kind, obj in ((EmployeeEntryKind.ACCRUAL, None), (EmployeeEntryKind.PAYMENT, "Expense"),
                          (EmployeeEntryKind.REPAYMENT, "Income"), (EmployeeEntryKind.DEDUCTION, None)):
            b = button("+ " + kind.label, obj)
            b.clicked.connect(lambda _=False, k=kind: self._add_entry(k))
            self.entry_buttons.append(b)
            acts.addWidget(b)
        acts.addStretch(1)
        right.body.addLayout(acts)
        self.ledger = QTableWidget(0, 5)
        self.ledger.setHorizontalHeaderLabels(["Tarih", "Hareket", "Açıklama", "Ödeme", "Tutar"])
        configure_table(self.ledger)
        self.ledger.horizontalHeader().setSectionResizeMode(2, self.ledger.horizontalHeader().ResizeMode.Stretch)
        self.ledger.setMinimumHeight(300)
        right.body.addWidget(self.ledger)
        foot = QHBoxLayout()
        self.ledger_info = label("", "Faint", wrap=True)
        foot.addWidget(self.ledger_info, 1)
        self.del_btn = button("Hareketi sil", "Danger", icon="trash", icon_color=theme.DANGER)
        self.del_btn.clicked.connect(self._delete_entry)
        foot.addWidget(self.del_btn)
        right.body.addLayout(foot)
        grid.addWidget(right, 3)
        self.stack.addWidget(body)
        self.content.addWidget(self.stack, 1)

        self._employees: list[Employee] = []
        self._entries = []
        self._selected_id: int | None = None

    # --- data ---------------------------------------------------------------------
    def params(self):
        return self.show_inactive.isChecked(), self._selected_id

    def load(self, p):
        include_inactive, selected = p
        emps = self.ctx.employees.employees(include_inactive=True)
        shown = [e for e in emps if e.active or include_inactive]
        if selected is None or all(e.id != selected for e in shown):
            selected = shown[0].id if shown else None
        entries = self.ctx.employees.entries(selected) if selected else []
        return emps, shown, selected, entries, self.ctx.employees.summary(), self.ctx.catalog.payment_methods()

    def apply(self, d):
        emps, shown, selected, entries, summary, methods = d
        self._methods = methods
        self.c_owed.set_amount(summary.owed_to_staff)
        self.c_due.set_amount(summary.owed_by_staff)
        self.c_count.value.setText(str(summary.active_count))
        self.stack.setCurrentIndex(1 if emps else 0)
        self._employees, self._entries, self._selected_id = shown, entries, selected

        self.list.blockSignals(True)
        self.list.setRowCount(0)
        for e in shown:
            text, color = _balance_text(e.balance)
            _row(self.list, [e.name + ("" if e.active else " (ayrıldı)"), e.role, text], {2: color})
        idx = next((i for i, e in enumerate(shown) if e.id == selected), -1)
        if idx >= 0:
            self.list.selectRow(idx)
        self.list.blockSignals(False)
        self._show_employee(next((e for e in shown if e.id == selected), None))

    def _show_employee(self, e: Employee | None):
        has = e is not None
        for w in (self.edit_btn, self.del_btn, *self.entry_buttons):
            w.setEnabled(has)
        self.ledger.setRowCount(0)
        if not has:
            self.emp_title.setText("Personel seçin")
            self.emp_info.clear()
            self.balance_lbl.clear()
            self.ledger_info.clear()
            return
        self.emp_title.setText(e.name)
        info = [x for x in (e.role, e.phone, f"Maaş: {format_amount(e.monthly_salary)}" if e.monthly_salary else "")
                if x]
        self.emp_info.setText("  ·  ".join(info))
        _, color = _balance_text(e.balance)
        self.balance_lbl.setText(balance_sentence(e.name, e.balance))
        self.balance_lbl.setStyleSheet(f"font-size: 13pt; font-weight: 600; color: {color};")
        for en in self._entries:
            sign = "+" if en.kind.sign > 0 else "−"
            color = theme.WARNING if en.kind.sign > 0 else theme.INFO
            _row(self.ledger, [en.occurred_on.strftime("%d.%m.%Y"), en.kind.label, en.description,
                               en.payment_method_name or "—", f"{sign}{format_amount(en.amount)}"], {4: color})
        self.ledger_info.setText("“+” personelin alacağını artırır, “−” azaltır. Ödeme ve tahsilatlar kasaya ve "
                                 "giderlere otomatik işlenir.")

    def _selection_changed(self):
        rows = self.list.selectionModel().selectedRows()
        if rows:
            self._selected_id = self._employees[rows[0].row()].id
            self.refresh()

    def _current(self) -> Employee | None:
        return next((e for e in self._employees if e.id == self._selected_id), None)

    # --- actions ------------------------------------------------------------------
    def _done(self, msg):
        self.window_.notify(msg)
        self.window_.data_changed()

    def _add_employee(self):
        dlg = EmployeeDialog(self)
        if dlg.exec() and dlg.result_employee:
            emp = dlg.result_employee

            def saved(e):
                self._selected_id = e.id
                self._done("Personel eklendi.")
            run_async(lambda: self.ctx.employees.add(emp), saved,
                      lambda e: show_error(self, "Personel eklenemedi", e), owner=self)

    def _edit_employee(self):
        e = self._current()
        if not e:
            return
        dlg = EmployeeDialog(self, e)
        if dlg.exec() and dlg.result_employee:
            emp = dlg.result_employee
            run_async(lambda: self.ctx.employees.update(emp), lambda _: self._done("Personel güncellendi."),
                      lambda err: show_error(self, "Güncellenemedi", err), owner=self)

    def _add_entry(self, kind: EmployeeEntryKind):
        e = self._current()
        if not e:
            return
        if kind.moves_cash and not getattr(self, "_methods", None):
            show_error(self, "Ödeme yöntemi yok", "Ayarlar'dan en az bir aktif ödeme yöntemi ekleyin.")
            return
        if EntryDialog(self, self.ctx, e, kind, self._methods).exec():
            self._done(f"{kind.label} kaydedildi.")

    def _delete_entry(self):
        r = self.ledger.currentRow()
        if not 0 <= r < len(self._entries):
            show_error(self, "Hareket seçin", "Silmek için listeden bir hareket seçin.")
            return
        en = self._entries[r]
        extra = "\n\nBağlı kasa/gider kaydı da silinecek." if en.transaction_id else ""
        if not confirm(self, "Hareketi sil", f"{en.occurred_on:%d.%m.%Y} tarihli {format_amount(en.amount)} "
                                             f"tutarındaki “{en.kind.label}” hareketi silinsin mi?{extra}",
                       "Sil", danger=True):
            return
        run_async(lambda: self.ctx.employees.delete_entry(en.id), lambda _: self._done("Hareket silindi."),
                  lambda err: show_error(self, "Silinemedi", err), owner=self)
