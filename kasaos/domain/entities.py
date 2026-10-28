from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from kasaos.domain.enums import AccountKind, CategoryKind, EmployeeEntryKind, TxKind


@dataclass
class Account:
    id: int
    name: str
    kind: AccountKind
    opening_balance: int
    active: bool = True


@dataclass
class Category:
    id: int
    name: str
    kind: CategoryKind
    color: str = "#C9A227"
    active: bool = True


@dataclass
class PaymentMethod:
    id: int
    name: str
    account_id: int
    active: bool = True


@dataclass
class Transaction:
    id: str
    kind: TxKind
    occurred_on: date
    occurred_time: str
    amount: int  # kuruş, always positive
    account_id: int
    category_id: int | None = None
    payment_method_id: int | None = None
    to_account_id: int | None = None
    description: str = ""
    note: str = ""
    is_refund: bool = False
    created_at: str = ""
    updated_at: str = ""
    # denormalised display names, filled by queries
    category_name: str = ""
    payment_method_name: str = ""
    account_name: str = ""
    to_account_name: str = ""


@dataclass
class TransactionDraft:
    """User input for creating/updating a transaction, validated by the service."""
    kind: TxKind
    occurred_on: date
    amount: int
    account_id: int | None = None
    category_id: int | None = None
    payment_method_id: int | None = None
    to_account_id: int | None = None
    description: str = ""
    note: str = ""
    is_refund: bool = False
    occurred_time: str = ""


@dataclass
class TransactionFilter:
    date_from: date | None = None
    date_to: date | None = None
    kinds: tuple[TxKind, ...] = ()
    category_id: int | None = None
    payment_method_id: int | None = None
    account_id: int | None = None
    text: str = ""
    limit: int | None = None


@dataclass
class CashSession:
    id: int
    account_id: int
    business_date: date
    opening_amount: int
    opened_at: str
    counted_amount: int | None = None
    expected_amount: int | None = None
    closed_at: str | None = None
    note: str = ""

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    @property
    def difference(self) -> int | None:
        if self.counted_amount is None or self.expected_amount is None:
            return None
        return self.counted_amount - self.expected_amount


@dataclass
class PeriodSummary:
    income: int = 0
    expense: int = 0
    owner_withdrawals: int = 0
    owner_deposits: int = 0
    transfers: int = 0
    card_income: int = 0
    cash_income: int = 0
    income_count: int = 0
    expense_count: int = 0

    @property
    def net(self) -> int:
        """Income minus expenses for the period. Not an official profit figure."""
        return self.income - self.expense


@dataclass
class DailyPoint:
    day: date
    income: int = 0
    expense: int = 0


@dataclass
class CategoryTotal:
    category_id: int | None
    name: str
    color: str
    amount: int
    count: int = 0


@dataclass
class Employee:
    id: int
    name: str
    role: str = ""
    phone: str = ""
    monthly_salary: int = 0  # kuruş, informational / default accrual amount
    note: str = ""
    active: bool = True
    pay_type: str = "monthly"  # "monthly" | "daily"
    daily_wage: int = 0        # kuruş, used by Günlük Yoklama
    balance: int = 0           # filled by the service: >0 business owes, <0 employee owes

    @property
    def is_daily(self) -> bool:
        return self.pay_type == "daily"

    @property
    def wage_text(self) -> str:
        from kasaos.domain.money import format_amount
        if self.is_daily:
            return f"Günlük {format_amount(self.daily_wage)}" if self.daily_wage else "Günlük ücretli"
        return f"Aylık {format_amount(self.monthly_salary)}" if self.monthly_salary else ""


@dataclass
class EmployeeEntry:
    id: str
    employee_id: int
    kind: "EmployeeEntryKind"
    amount: int
    occurred_on: date
    description: str = ""
    transaction_id: str | None = None
    payment_method_name: str = ""
    created_at: str = ""
    work_day: bool = False

    @property
    def signed(self) -> int:
        return self.kind.sign * self.amount


@dataclass
class AuditEvent:
    id: int
    at: str
    entity: str
    entity_id: str
    action: str
    details: dict = field(default_factory=dict)
