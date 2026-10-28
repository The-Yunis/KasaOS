"""Accounting rules shared by every calculation. Keep business rules here only.

Sign conventions (effect on an account balance, in kuruş):

    income            +amount on account   (refund: -amount)
    expense           -amount on account   (refund: +amount)
    owner_withdrawal  -amount on account   (not an expense)
    owner_deposit     +amount on account   (not income)
    transfer          -amount on account, +amount on to_account (not income/expense)
"""

from __future__ import annotations

from kasaos.domain.enums import TxKind


def account_effects(kind: TxKind, amount: int, account_id: int, to_account_id: int | None,
                    is_refund: bool = False) -> dict[int, int]:
    effects: dict[int, int] = {}

    def add(acc: int, v: int) -> None:
        effects[acc] = effects.get(acc, 0) + v

    if kind == TxKind.INCOME:
        add(account_id, -amount if is_refund else amount)
    elif kind == TxKind.EXPENSE:
        add(account_id, amount if is_refund else -amount)
    elif kind == TxKind.OWNER_WITHDRAWAL:
        add(account_id, -amount)
    elif kind == TxKind.OWNER_DEPOSIT:
        add(account_id, amount)
    elif kind == TxKind.TRANSFER:
        if to_account_id is None:
            raise ValueError("transfer requires to_account_id")
        add(account_id, -amount)
        add(to_account_id, amount)
    return effects


def signed_income(kind: TxKind, amount: int, is_refund: bool) -> int:
    """Contribution of a transaction to period income (refunds reduce it)."""
    if kind != TxKind.INCOME:
        return 0
    return -amount if is_refund else amount


def signed_expense(kind: TxKind, amount: int, is_refund: bool) -> int:
    if kind != TxKind.EXPENSE:
        return 0
    return -amount if is_refund else amount


def expected_closing_cash(opening_count: int, movements: list[int]) -> int:
    """Expected cash = counted opening + all signed cash movements of the day."""
    return opening_count + sum(movements)
