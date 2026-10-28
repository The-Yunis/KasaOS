"""Snapshot of reference data (categories, methods, accounts) for forms and filters."""

from __future__ import annotations

from dataclasses import dataclass

from kasaos.core.application_context import AppContext
from kasaos.domain.entities import Account, Category, PaymentMethod
from kasaos.domain.enums import CategoryKind


@dataclass
class ReferenceData:
    income_categories: list[Category]
    expense_categories: list[Category]
    all_categories: list[Category]
    methods: list[PaymentMethod]
    accounts: list[Account]
    default_income_method: int | None
    default_expense_method: int | None


def load_reference(ctx: AppContext) -> ReferenceData:
    def _int(v: str) -> int | None:
        return int(v) if v.isdigit() else None
    return ReferenceData(
        income_categories=ctx.catalog.categories(CategoryKind.INCOME),
        expense_categories=ctx.catalog.categories(CategoryKind.EXPENSE),
        all_categories=ctx.catalog.categories(include_inactive=True),
        methods=ctx.catalog.payment_methods(),
        accounts=ctx.catalog.accounts(),
        default_income_method=_int(ctx.settings.get("default_income_method")),
        default_expense_method=_int(ctx.settings.get("default_expense_method")),
    )
