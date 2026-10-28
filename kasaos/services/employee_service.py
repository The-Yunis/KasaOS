"""Personnel and their running balance (alacak / borç).

Balance = Σ accrual + Σ repayment − Σ payment − Σ deduction.
  > 0  the business owes the employee   (personel alacaklı)
  < 0  the employee owes the business   (personel borçlu)

Cash-moving entries create a linked transaction in the same DB transaction so
cash balances and reports stay consistent:
  payment   → expense in category "Personel"
  repayment → expense refund in "Personel" (reduces personnel cost)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from kasaos.core.exceptions import NotFoundError, ValidationError
from kasaos.domain.entities import Employee, EmployeeEntry, Transaction
from kasaos.domain.enums import CategoryKind, EmployeeEntryKind, TxKind
from kasaos.domain.money import MAX_AMOUNT_KURUS, format_amount
from kasaos.infrastructure.database import repositories as repo
from kasaos.infrastructure.database.connection import Database

log = logging.getLogger(__name__)

PERSONNEL_CATEGORY = "Personel"


@dataclass
class AttendanceRow:
    employee_id: int
    wage: int        # kuruş for this day
    paid: bool = False


@dataclass
class PersonnelSummary:
    owed_to_staff: int = 0     # Σ positive balances
    owed_by_staff: int = 0     # Σ |negative balances|
    active_count: int = 0


def balance_sentence(name: str, balance: int) -> str:
    if balance > 0:
        return f"{name} adlı personele {format_amount(balance)} borçlusunuz."
    if balance < 0:
        return f"{name} size {format_amount(-balance)} borçlu."
    return f"{name} ile hesap kapalı (bakiye sıfır)."


def _clean(e: Employee) -> Employee:
    e.name = (e.name or "").strip()
    e.role = (e.role or "").strip()
    e.phone = (e.phone or "").strip()
    e.note = (e.note or "").strip()
    if not e.name:
        raise ValidationError("Personel adı boş olamaz.", "name")
    if len(e.name) > 80 or len(e.role) > 60 or len(e.phone) > 30 or len(e.note) > 500:
        raise ValidationError("Alanlardan biri izin verilen uzunluğu aşıyor.", "name")
    if not isinstance(e.monthly_salary, int) or not 0 <= e.monthly_salary <= MAX_AMOUNT_KURUS:
        raise ValidationError("Maaş tutarı geçersiz.", "salary")
    if e.pay_type not in ("monthly", "daily"):
        raise ValidationError("Çalışma şekli geçersiz.", "pay_type")
    if not isinstance(e.daily_wage, int) or not 0 <= e.daily_wage <= MAX_AMOUNT_KURUS:
        raise ValidationError("Günlük ücret geçersiz.", "salary")
    return e


class EmployeeService:
    def __init__(self, db: Database):
        self.db = db

    # -- employees ---------------------------------------------------------------
    def employees(self, include_inactive: bool = True) -> list[Employee]:
        with self.db.read() as c:
            emps = repo.list_employees(c, include_inactive)
            bals = repo.employee_balances(c)
        for e in emps:
            e.balance = bals.get(e.id, 0)
        return emps

    def get(self, employee_id: int) -> Employee:
        with self.db.read() as c:
            e = repo.get_employee(c, employee_id)
            if e is None:
                raise NotFoundError("Personel bulunamadı.")
            e.balance = repo.employee_balances(c).get(employee_id, 0)
        return e

    def add(self, e: Employee) -> Employee:
        e = _clean(e)
        with self.db.transaction() as c:
            eid = repo.insert_employee(c, e)
            repo.add_audit(c, "employee", str(eid), "create", {"name": e.name})
        log.info("Employee created id=%s", eid)
        return self.get(eid)

    def update(self, e: Employee) -> Employee:
        e = _clean(e)
        with self.db.transaction() as c:
            old = repo.get_employee(c, e.id)
            if old is None:
                raise NotFoundError("Personel bulunamadı.")
            repo.update_employee(c, e)
            repo.add_audit(c, "employee", str(e.id), "update",
                           {"before": {"name": old.name, "active": old.active},
                            "after": {"name": e.name, "active": e.active}})
        return self.get(e.id)

    def summary(self) -> PersonnelSummary:
        s = PersonnelSummary()
        for e in self.employees():
            if e.active:
                s.active_count += 1
            if e.balance > 0:
                s.owed_to_staff += e.balance
            else:
                s.owed_by_staff -= e.balance
        return s

    # -- ledger ------------------------------------------------------------------
    def entries(self, employee_id: int) -> list[EmployeeEntry]:
        with self.db.read() as c:
            return repo.list_employee_entries(c, employee_id)

    def add_entry(self, employee_id: int, kind: EmployeeEntryKind, amount: int, occurred_on: date,
                  description: str = "", payment_method_id: int | None = None) -> EmployeeEntry:
        with self.db.transaction() as c:
            entry_id = self._insert(c, employee_id, kind, amount, occurred_on, description, payment_method_id)
            saved = repo.get_employee_entry(c, entry_id)
        log.info("Employee entry created id=%s kind=%s", entry_id, kind.value)
        return saved

    # -- Günlük Yoklama (daily attendance) -----------------------------------------
    def worked_on(self, day: date) -> set[int]:
        with self.db.read() as c:
            return repo.worked_employee_ids(c, day)

    def worked_days(self, employee_id: int, date_from: date, date_to: date) -> int:
        with self.db.read() as c:
            return repo.worked_days(c, employee_id, date_from, date_to)

    def record_attendance(self, day: date, rows: list[AttendanceRow], payment_method_id: int | None) -> int:
        """Accrue one day's wage for each row (and pay it if row.paid). All-or-nothing."""
        if not rows:
            raise ValidationError("Çalışan en az bir personel seçin.")
        if any(r.paid for r in rows) and payment_method_id is None:
            raise ValidationError("Ödeme yöntemi seçiniz.", "payment_method")
        with self.db.transaction() as c:
            already = repo.worked_employee_ids(c, day)
            for r in rows:
                emp = repo.get_employee(c, r.employee_id)
                if emp is None:
                    raise NotFoundError("Personel bulunamadı.")
                if r.employee_id in already:
                    raise ValidationError(f"{emp.name} için {day:%d.%m.%Y} yevmiyesi zaten yazılmış.")
                self._insert(c, r.employee_id, EmployeeEntryKind.ACCRUAL, r.wage, day, "Günlük ücret",
                             work_day=True)
                if r.paid:
                    self._insert(c, r.employee_id, EmployeeEntryKind.PAYMENT, r.wage, day, "Günlük ücret ödemesi",
                                 payment_method_id)
                already.add(r.employee_id)
        log.info("Attendance recorded day=%s count=%s", day, len(rows))
        return len(rows)

    # -- internal ------------------------------------------------------------------
    def _insert(self, c, employee_id: int, kind: EmployeeEntryKind, amount: int, occurred_on: date,
                description: str = "", payment_method_id: int | None = None, work_day: bool = False) -> str:
        if not isinstance(kind, EmployeeEntryKind):
            raise ValidationError("Geçersiz hareket türü.", "kind")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValidationError("Tutar sıfırdan büyük olmalıdır.", "amount")
        if amount > MAX_AMOUNT_KURUS:
            raise ValidationError("Tutar izin verilen üst sınırı aşıyor.", "amount")
        if not isinstance(occurred_on, date) or occurred_on > date.today() + timedelta(days=7) \
                or occurred_on.year < 2000:
            raise ValidationError("Geçerli bir tarih seçiniz.", "date")
        description = (description or "").strip()
        if len(description) > 500:
            raise ValidationError("Açıklama en fazla 500 karakter olabilir.", "description")
        if kind.moves_cash and payment_method_id is None:
            raise ValidationError("Ödeme yöntemi seçiniz.", "payment_method")

        now = repo.utc_now()
        emp = repo.get_employee(c, employee_id)
        if emp is None:
            raise NotFoundError("Personel bulunamadı.")
        tx_id = None
        if kind.moves_cash:
            pm = repo.get_payment_method(c, payment_method_id)
            if pm is None:
                raise ValidationError("Ödeme yöntemi bulunamadı.", "payment_method")
            cat = self._personnel_category(c)
            tx_id = str(uuid.uuid4())
            label = "Avans / ödeme" if kind == EmployeeEntryKind.PAYMENT else "Personelden tahsilat"
            repo.insert_transaction(c, Transaction(
                id=tx_id, kind=TxKind.EXPENSE, occurred_on=occurred_on,
                occurred_time=datetime.now().strftime("%H:%M"), amount=amount, account_id=pm.account_id,
                category_id=cat, payment_method_id=pm.id,
                description=f"Personel: {emp.name} — {description or label}",
                is_refund=(kind == EmployeeEntryKind.REPAYMENT), created_at=now, updated_at=now))
            repo.add_audit(c, "transaction", tx_id, "create",
                           {"kind": "expense", "amount": amount, "employee_id": employee_id})
        entry = EmployeeEntry(str(uuid.uuid4()), employee_id, kind, amount, occurred_on, description, tx_id,
                              created_at=now, work_day=work_day)
        repo.insert_employee_entry(c, entry)
        repo.add_audit(c, "employee_entry", entry.id, "create",
                       {"employee_id": employee_id, "kind": kind.value, "amount": amount})
        return entry.id

    def delete_entry(self, entry_id: str) -> None:
        """Deleting an entry also removes its linked cash transaction."""
        with self.db.transaction() as c:
            e = repo.get_employee_entry(c, entry_id)
            if e is None:
                raise NotFoundError("Hareket bulunamadı veya zaten silinmiş.")
            repo.soft_delete_employee_entry(c, entry_id)
            repo.add_audit(c, "employee_entry", entry_id, "delete",
                           {"employee_id": e.employee_id, "kind": e.kind.value, "amount": e.amount})
            if e.transaction_id:
                repo.soft_delete_transaction(c, e.transaction_id)
                repo.add_audit(c, "transaction", e.transaction_id, "delete", {"via": "employee_entry"})

    @staticmethod
    def _personnel_category(c) -> int:
        cat = repo.find_category(c, PERSONNEL_CATEGORY, CategoryKind.EXPENSE)
        if cat is not None:
            if not cat.active:
                repo.update_category(c, cat.id, cat.name, cat.color, True)
            return cat.id
        return repo.insert_category(c, PERSONNEL_CATEGORY, CategoryKind.EXPENSE, "#D9774B")
