"""Personel — staff list, running balance (alacak / borç) and ledger."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

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
        self.pay_type = QComboBox()
        self.pay_type.addItem("Günlük ücret (yevmiye)", "daily")
        self.pay_type.addItem("Aylık maaş", "monthly")
        self.pay_type.setCurrentIndex(self.pay_type.findData(emp.pay_type if emp else "daily"))
        self.salary = QLineEdit()
        self.salary_label = QLabel()
        self.pay_type.currentIndexChanged.connect(self._pay_type_changed)
        self.note = QLineEdit(emp.note if emp else "")
        self.active = QCheckBox("Çalışıyor (aktif)")
        self.active.setChecked(emp.active if emp else True)
        form.addRow("Ad soyad", self.name)
        form.addRow("Görev", self.role)
        form.addRow("Telefon", self.phone)
        form.addRow("Çalışma şekli", self.pay_type)
        form.addRow(self.salary_label, self.salary)
        self._pay_type_changed()
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

    def _pay_type_changed(self):
        daily = self.pay_type.currentData() == "daily"
        self.salary_label.setText("Günlük ücret" if daily else "Aylık maaş")
        self.salary.setPlaceholderText("ör. 1.200,00" if daily else "İsteğe bağlı, ör. 25.000,00")
        value = 0
        if self.emp:
            value = self.emp.daily_wage if daily else self.emp.monthly_salary
        self.salary.setText(format_amount(value, symbol=False) if value else "")

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
        daily = self.pay_type.currentData() == "daily"
        if daily and not salary:
            self.err.setText("Günlük ücreti girin; Günlük Yoklama bu tutarı kullanır.")
            return
        keep_monthly = self.emp.monthly_salary if self.emp else 0
        keep_daily = self.emp.daily_wage if self.emp else 0
        self.result_employee = Employee(
            self.emp.id if self.emp else 0, self.name.text(), self.role.text(), self.phone.text(),
            keep_monthly if daily else salary, self.note.text(), self.active.isChecked(),
            "daily" if daily else "monthly", salary if daily else keep_daily)
        self.accept()


class AttendanceDialog(QDialog):
    """Günlük Yoklama: tick who worked on a day; accrue (and optionally pay) each daily wage at once."""

    def __init__(self, parent, ctx, employees: list[Employee], methods, worked: set[int], day: date):
        super().__init__(parent)
        self.ctx = ctx
        self._busy = False
        self.setWindowTitle("Günlük Yoklama")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Günlük Yoklama", "SectionTitle"))
        lay.addWidget(label("O gün çalışanları işaretleyin. Yevmiyeleri hak ediş olarak yazılır. Parasını aynı gün "
                            "alanlar için “Ödendi” işaretlenirse ödeme de kasadan düşülür.", "Muted", wrap=True))
        top = QHBoxLayout()
        top.addWidget(label("Tarih"))
        self.day = QDateEdit(QDate(day.year, day.month, day.day))
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd.MM.yyyy")
        self.day.dateChanged.connect(self._reload_worked)
        top.addWidget(self.day)
        top.addSpacing(16)
        top.addWidget(label("Ödeme yöntemi"))
        self.method = QComboBox()
        for m in methods:
            self.method.addItem(m.name, m.id)
        top.addWidget(self.method)
        top.addStretch(1)
        lay.addLayout(top)

        self.employees = employees
        self.table = QTableWidget(len(employees), 4)
        self.table.setHorizontalHeaderLabels(["Çalıştı", "Personel", "Yevmiye (₺)", "Ödendi"])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.setSelectionMode(self.table.SelectionMode.NoSelection)
        self.checks, self.wages, self.paid = [], [], []
        for r, e in enumerate(employees):
            cb = QCheckBox()
            cb.toggled.connect(self._update_total)
            wage = QLineEdit(format_amount(e.daily_wage, symbol=False))
            wage.setAlignment(Qt.AlignmentFlag.AlignRight)
            wage.textChanged.connect(self._update_total)
            paid = QCheckBox()
            paid.toggled.connect(self._update_total)
            self.table.setCellWidget(r, 0, _centered(cb))
            self.table.setItem(r, 1, QTableWidgetItem(e.name + (f" · {e.role}" if e.role else "")))
            self.table.setCellWidget(r, 2, wage)
            self.table.setCellWidget(r, 3, _centered(paid))
            self.checks.append(cb)
            self.wages.append(wage)
            self.paid.append(paid)
        self.table.setMinimumHeight(min(420, 60 + 40 * len(employees)))
        lay.addWidget(self.table)
        row = QHBoxLayout()
        all_btn = button("Hepsini işaretle", "Ghost")
        all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self.checks if cb.isEnabled()])
        row.addWidget(all_btn)
        row.addStretch(1)
        self.total = label("", "Muted")
        row.addWidget(self.total)
        lay.addLayout(row)
        self.err = label("", "ErrorText", wrap=True)
        lay.addWidget(self.err)
        btns = QHBoxLayout()
        cancel = button("Vazgeç")
        cancel.clicked.connect(self.reject)
        self.ok = button("Yoklamayı Kaydet", "Primary")
        self.ok.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addStretch(1)
        btns.addWidget(self.ok)
        lay.addLayout(btns)
        self._apply_worked(worked)

    def _selected_day(self) -> date:
        q = self.day.date()
        return date(q.year(), q.month(), q.day())

    def _reload_worked(self, *_):
        day = self._selected_day()
        run_async(lambda: self.ctx.employees.worked_on(day), self._apply_worked,
                  lambda e: show_error(self, "Yoklama yüklenemedi", e), owner=self)

    def _apply_worked(self, worked: set[int]):
        for r, (e, cb, wage, paid) in enumerate(zip(self.employees, self.checks, self.wages, self.paid)):
            done = e.id in worked
            item = self.table.item(r, 1)
            item.setText(e.name + (f" · {e.role}" if e.role else "") + ("   ✓ bu gün yazıldı" if done else ""))
            item.setForeground(QColor(theme.TEXT_FAINT if done else theme.TEXT))
            cb.blockSignals(True)
            cb.setChecked(done)
            cb.blockSignals(False)
            for w in (cb, wage, paid):
                w.setEnabled(not done)
            cb.setToolTip("Bu gün için yevmiye zaten yazılmış" if done else "")
        self._update_total()

    def _rows(self):
        rows = []
        for e, cb, wage, paid in zip(self.employees, self.checks, self.wages, self.paid):
            if cb.isChecked() and cb.isEnabled():
                rows.append((e, wage.text(), paid.isChecked()))
        return rows

    def _update_total(self, *_):
        total = paid_total = 0
        for _e, text, paid in self._rows():
            try:
                v = parse_amount(text)
            except ValidationError:
                continue
            total += v
            paid_total += v if paid else 0
        n = len(self._rows())
        self.total.setText(f"{n} kişi · Yevmiye toplamı {format_amount(total)} · Bugün ödenen {format_amount(paid_total)}")

    def _save(self):
        if self._busy:
            return
        from kasaos.services.employee_service import AttendanceRow
        rows = []
        for e, text, paid in self._rows():
            try:
                rows.append(AttendanceRow(e.id, parse_amount(text), paid))
            except ValidationError as err:
                self.err.setText(f"{e.name}: {err}")
                return
        if not rows:
            self.err.setText("Çalışan en az bir personel işaretleyin.")
            return
        day = self._selected_day()
        method = self.method.currentData()
        self._busy = True
        self.ok.setEnabled(False)
        self.ok.setText("Kaydediliyor…")

        def fail(e):
            self._busy = False
            self.ok.setEnabled(True)
            self.ok.setText("Yoklamayı Kaydet")
            if isinstance(e, ValidationError):
                self.err.setText(str(e))
            else:
                show_error(self, "Yoklama kaydedilemedi", e)
        run_async(lambda: self.ctx.employees.record_attendance(day, rows, method), lambda n: self.accept(), fail,
                  owner=self)


def _centered(widget) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(widget)
    return w


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
        default_accrual = emp.daily_wage if emp.is_daily else emp.monthly_salary
        if kind == EmployeeEntryKind.ACCRUAL and default_accrual:
            self.amount.setText(format_amount(default_accrual, symbol=False))
        if kind == EmployeeEntryKind.PAYMENT and emp.balance > 0:
            self.amount.setText(format_amount(emp.balance, symbol=False))  # pay what is owed
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
        self.attendance_btn = button("Günlük Yoklama", "Income", icon="personnel", icon_color=theme.INCOME)
        self.attendance_btn.setToolTip("Bugün çalışan günlükçülerin yevmiyesini tek seferde yazın")
        self.attendance_btn.clicked.connect(self._attendance)
        header.actions.addWidget(self.attendance_btn)
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
        today = date.today()
        days = self.ctx.employees.worked_days(selected, today.replace(day=1), today) if selected else 0
        return (emps, shown, selected, entries, self.ctx.employees.summary(), self.ctx.catalog.payment_methods(),
                days)

    def apply(self, d):
        emps, shown, selected, entries, summary, methods, days = d
        self._methods = methods
        self._month_days = days
        self.attendance_btn.setEnabled(any(e.active and e.is_daily for e in emps))
        self.c_owed.set_amount(summary.owed_to_staff)
        self.c_due.set_amount(summary.owed_by_staff)
        self.c_count.value.setText(str(summary.active_count))
        self.stack.setCurrentIndex(1 if emps else 0)
        self._employees, self._entries, self._selected_id = shown, entries, selected

        self.list.blockSignals(True)
        self.list.setRowCount(0)
        for e in shown:
            text, color = _balance_text(e.balance)
            role = " · ".join(x for x in (e.role, e.wage_text) if x)
            _row(self.list, [e.name + ("" if e.active else " (ayrıldı)"), role, text], {2: color})
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
        info = [x for x in (e.role, e.phone, e.wage_text,
                            f"Bu ay {self._month_days} gün çalıştı" if e.is_daily else "") if x]
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

    def _attendance(self):
        if not getattr(self, "_methods", None):
            show_error(self, "Ödeme yöntemi yok", "Ayarlar'dan en az bir aktif ödeme yöntemi ekleyin.")
            return
        today = date.today()

        def open_dialog(data):
            emps, worked = data
            daily = [e for e in emps if e.active and e.is_daily]
            if not daily:
                show_error(self, "Günlükçü personel yok",
                           "Personeli düzenleyip çalışma şeklini “Günlük ücret” olarak ayarlayın.")
                return
            if AttendanceDialog(self, self.ctx, daily, self._methods, worked, today).exec():
                self._done("Yoklama kaydedildi.")
        run_async(lambda: (self.ctx.employees.employees(include_inactive=False), self.ctx.employees.worked_on(today)),
                  open_dialog, lambda e: show_error(self, "Yoklama açılamadı", e), owner=self)

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
