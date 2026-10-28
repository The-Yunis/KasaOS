from __future__ import annotations

from enum import StrEnum


class TxKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"                # between own accounts, never income/expense
    OWNER_WITHDRAWAL = "owner_withdrawal"  # personal draw, not an operating expense
    OWNER_DEPOSIT = "owner_deposit"        # capital put in, not income

    @property
    def label(self) -> str:
        return TX_KIND_LABELS[self]


TX_KIND_LABELS = {
    TxKind.INCOME: "Gelir",
    TxKind.EXPENSE: "Gider",
    TxKind.TRANSFER: "Hesaplar Arası Transfer",
    TxKind.OWNER_WITHDRAWAL: "Sahip Çekişi",
    TxKind.OWNER_DEPOSIT: "Sermaye Girişi",
}


class AccountKind(StrEnum):
    CASH = "cash"
    BANK = "bank"
    POS = "pos"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {"cash": "Nakit Kasa", "bank": "Banka", "pos": "POS / Kart", "other": "Diğer"}[self.value]


class EmployeeEntryKind(StrEnum):
    """Personnel ledger. Balance > 0: the business owes the employee; < 0: the employee owes."""
    ACCRUAL = "accrual"        # hak ediş (maaş, prim, mesai) — no cash movement
    PAYMENT = "payment"        # ödeme / avans — cash out, recorded as a "Personel" expense
    REPAYMENT = "repayment"    # personelden tahsilat — cash in, reduces the "Personel" expense
    DEDUCTION = "deduction"    # kesinti / personele borç yazma — no cash movement

    @property
    def label(self) -> str:
        return {"accrual": "Hak ediş", "payment": "Ödeme / Avans", "repayment": "Tahsilat",
                "deduction": "Kesinti"}[self.value]

    @property
    def sign(self) -> int:
        return 1 if self in (EmployeeEntryKind.ACCRUAL, EmployeeEntryKind.REPAYMENT) else -1

    @property
    def moves_cash(self) -> bool:
        return self in (EmployeeEntryKind.PAYMENT, EmployeeEntryKind.REPAYMENT)


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
