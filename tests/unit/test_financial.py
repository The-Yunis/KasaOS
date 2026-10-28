from datetime import date, timedelta

import pytest

from kasaos.core.exceptions import NotFoundError, ValidationError
from kasaos.domain.entities import TransactionDraft, TransactionFilter
from kasaos.domain.enums import CategoryKind, TxKind


def test_income_expense_net(ctx, h):
    h.income(100_00)
    h.income(250_50, method="Kredi kartı")
    h.expense(80_25)
    s = ctx.reports.summary(date.today(), date.today())
    assert s.income == 350_50
    assert s.expense == 80_25
    assert s.net == 270_25
    assert s.card_income == 250_50
    assert s.cash_income == 100_00


def test_transfer_and_withdrawal_not_income_or_expense(ctx, h):
    h.income(1000_00)
    h.transfer(400_00, "cash", "bank")
    h.withdrawal(100_00)
    s = ctx.reports.summary(None, None)
    assert s.income == 1000_00
    assert s.expense == 0
    assert s.transfers == 400_00
    assert s.owner_withdrawals == 100_00
    assert ctx.cash.balance(h.accounts["cash"].id) == 500_00
    assert ctx.cash.balance(h.accounts["bank"].id) == 400_00


def test_refunds_reduce_totals(ctx, h):
    h.income(500_00)
    h.income(50_00, refund=True)
    h.expense(200_00)
    h.expense(20_00, refund=True)
    s = ctx.reports.summary(None, None)
    assert s.income == 450_00
    assert s.expense == 180_00
    assert ctx.cash.balance(h.accounts["cash"].id) == 500_00 - 50_00 - 200_00 + 20_00


def test_opening_balance_counts_in_balance(ctx, h):
    acc = h.accounts["cash"]
    ctx.catalog.update_account(acc.id, acc.name, 1_000_00, True)
    h.expense(300_00)
    assert ctx.cash.balance(acc.id) == 700_00


def test_date_boundaries(ctx, h):
    today = date.today()
    h.income(10_00, day=today - timedelta(days=1))
    h.income(20_00, day=today)
    h.income(40_00, day=today - timedelta(days=2))
    assert ctx.reports.summary(today, today).income == 20_00
    assert ctx.reports.summary(today - timedelta(days=1), today).income == 30_00
    daily = ctx.reports.daily(today - timedelta(days=2), today)
    assert [p.income for p in daily] == [40_00, 10_00, 20_00]


def test_category_filter_and_breakdown(ctx, h):
    sales = h.cat(CategoryKind.INCOME, "Satış")
    other = h.cat(CategoryKind.INCOME, "Nargile")
    h.income(100_00, cat=sales)
    h.income(70_00, cat=other)
    h.income(30_00, cat=sales)
    txs = ctx.transactions.list(TransactionFilter(category_id=sales.id))
    assert sum(t.amount for t in txs) == 130_00
    breakdown = ctx.reports.by_category(CategoryKind.INCOME, None, None)
    assert [(b.name, b.amount) for b in breakdown] == [("Satış", 130_00), ("Nargile", 70_00)]


def test_report_totals_match_transactions(ctx, h):
    for i in range(1, 30):
        h.income(i * 101)
        h.expense(i * 37, method="Banka transferi")
    s = ctx.reports.summary(None, None)
    pm = ctx.reports.by_payment_method(None, None)
    assert s.income == sum(r[1] for r in pm)
    assert s.expense == sum(r[2] for r in pm)


def test_validation_rejects_bad_input(ctx, h):
    inc_cat = h.cat(CategoryKind.INCOME)
    exp_cat = h.cat(CategoryKind.EXPENSE)
    nakit = h.methods["Nakit"].id
    bad = [
        TransactionDraft(TxKind.INCOME, date.today(), 0, category_id=inc_cat.id, payment_method_id=nakit),
        TransactionDraft(TxKind.INCOME, date.today(), -5, category_id=inc_cat.id, payment_method_id=nakit),
        TransactionDraft(TxKind.INCOME, date.today(), 100, category_id=exp_cat.id, payment_method_id=nakit),
        TransactionDraft(TxKind.INCOME, date.today(), 100, category_id=None, payment_method_id=nakit),
        TransactionDraft(TxKind.INCOME, date.today(), 100, category_id=inc_cat.id, payment_method_id=None),
        TransactionDraft(TxKind.INCOME, date.today() + timedelta(days=60), 100, category_id=inc_cat.id,
                         payment_method_id=nakit),
        TransactionDraft(TxKind.TRANSFER, date.today(), 100, account_id=h.accounts["cash"].id,
                         to_account_id=h.accounts["cash"].id),
        TransactionDraft(TxKind.EXPENSE, date.today(), 10.5, category_id=exp_cat.id, payment_method_id=nakit),
    ]
    for d in bad:
        with pytest.raises(ValidationError):
            ctx.transactions.create(d)
    assert ctx.transactions.list(TransactionFilter()) == []


def test_update_and_delete_are_audited(ctx, h):
    t = h.expense(100_00)
    d = TransactionDraft(TxKind.EXPENSE, t.occurred_on, 150_00, category_id=t.category_id,
                         payment_method_id=t.payment_method_id, description="düzeltme")
    updated = ctx.transactions.update(t.id, d)
    assert updated.amount == 150_00 and updated.description == "düzeltme"
    ctx.transactions.delete(t.id)
    assert ctx.transactions.get(t.id) is None
    actions = [e.action for e in ctx.transactions.history(t.id)]
    assert actions == ["delete", "update", "create"]
    with pytest.raises(NotFoundError):
        ctx.transactions.delete(t.id)
    assert ctx.reports.summary(None, None).expense == 0


def test_search_text_and_kind_filter(ctx, h):
    h.ctx.transactions.create(TransactionDraft(
        TxKind.EXPENSE, date.today(), 10_00, category_id=h.cat(CategoryKind.EXPENSE).id,
        payment_method_id=h.methods["Nakit"].id, description="Çay şekeri %50"))
    h.income(5_00)
    assert len(ctx.transactions.list(TransactionFilter(text="şeker"))) == 1
    assert len(ctx.transactions.list(TransactionFilter(text="%50"))) == 1
    assert len(ctx.transactions.list(TransactionFilter(text="_"))) == 0
    assert len(ctx.transactions.list(TransactionFilter(kinds=(TxKind.INCOME,)))) == 1


def test_cash_session_expected_and_discrepancy(ctx, h):
    cash = h.accounts["cash"].id
    today = date.today()
    ctx.cash.open_session(cash, today, 500_00)
    h.income(1_000_00)
    h.income(300_00, method="Kredi kartı")   # not cash
    h.expense(200_00)
    h.transfer(400_00, "cash", "bank")
    h.withdrawal(50_00)
    session = ctx.cash.session(cash, today)
    assert ctx.cash.expected_cash(session) == 500_00 + 1_000_00 - 200_00 - 400_00 - 50_00
    closed = ctx.cash.close_session(cash, today, 840_00, "eksik")
    assert closed.expected_amount == 850_00
    assert closed.difference == -10_00
    with pytest.raises(ValidationError):
        ctx.cash.close_session(cash, today, 840_00)
    with pytest.raises(ValidationError):
        ctx.cash.open_session(cash, today, 0)


def test_category_rules(ctx):
    cat = ctx.catalog.add_category("Etkinlik", CategoryKind.INCOME, "#AABBCC")
    with pytest.raises(ValidationError):
        ctx.catalog.add_category("etkinlik", CategoryKind.INCOME)
    ctx.catalog.add_category("Etkinlik", CategoryKind.EXPENSE)  # same name, other kind is fine
    ctx.catalog.delete_category(cat.id)
    assert all(c.id != cat.id for c in ctx.catalog.categories())


def test_used_category_cannot_be_deleted(ctx, h):
    cat = h.cat(CategoryKind.EXPENSE)
    h.expense(10_00, cat=cat)
    with pytest.raises(ValidationError):
        ctx.catalog.delete_category(cat.id)
    ctx.catalog.update_category(cat.id, cat.name, cat.color, active=False)
    assert all(c.id != cat.id for c in ctx.catalog.categories(CategoryKind.EXPENSE))
