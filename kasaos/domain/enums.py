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


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
