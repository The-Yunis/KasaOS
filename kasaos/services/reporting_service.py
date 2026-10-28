"""Period totals, daily series and category breakdowns, from persisted data only."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from kasaos.domain.entities import CategoryTotal, DailyPoint, PeriodSummary, TransactionFilter
from kasaos.domain.enums import AccountKind, CategoryKind, TxKind
from kasaos.domain.financial_rules import signed_expense, signed_income
from kasaos.domain.money import format_amount
from kasaos.infrastructure.database import repositories as repo
from kasaos.infrastructure.database.connection import Database


class ReportingService:
    def __init__(self, db: Database):
        self.db = db

    def summary(self, date_from: date | None, date_to: date | None) -> PeriodSummary:
        with self.db.read() as c:
            rows = repo.transactions_for_accounting(c, date_from, date_to)
        s = PeriodSummary()
        for r in rows:
            kind, amount, refund = TxKind(r["kind"]), r["amount"], bool(r["is_refund"])
            inc = signed_income(kind, amount, refund)
            exp = signed_expense(kind, amount, refund)
            s.income += inc
            s.expense += exp
            if kind == TxKind.INCOME:
                s.income_count += 1
                if r["account_kind"] == AccountKind.CASH.value:
                    s.cash_income += inc
                elif r["account_kind"] == AccountKind.POS.value:
                    s.card_income += inc
            elif kind == TxKind.EXPENSE:
                s.expense_count += 1
            elif kind == TxKind.OWNER_WITHDRAWAL:
                s.owner_withdrawals += amount
            elif kind == TxKind.OWNER_DEPOSIT:
                s.owner_deposits += amount
            elif kind == TxKind.TRANSFER:
                s.transfers += amount
        return s

    def daily(self, date_from: date, date_to: date) -> list[DailyPoint]:
        with self.db.read() as c:
            rows = repo.transactions_for_accounting(c, date_from, date_to)
        points: dict[date, DailyPoint] = {}
        d = date_from
        while d <= date_to:
            points[d] = DailyPoint(d)
            d += timedelta(days=1)
        for r in rows:
            day = date.fromisoformat(r["occurred_on"])
            kind, amount, refund = TxKind(r["kind"]), r["amount"], bool(r["is_refund"])
            p = points[day]
            p.income += signed_income(kind, amount, refund)
            p.expense += signed_expense(kind, amount, refund)
        return list(points.values())

    def by_category(self, kind: CategoryKind, date_from: date | None, date_to: date | None) -> list[CategoryTotal]:
        with self.db.read() as c:
            cats = {cat.id: cat for cat in repo.list_categories(c, kind, include_inactive=True)}
            rows = repo.transactions_for_accounting(c, date_from, date_to)
        tx_kind = TxKind.INCOME if kind == CategoryKind.INCOME else TxKind.EXPENSE
        totals: dict[int | None, CategoryTotal] = {}
        for r in rows:
            if r["kind"] != tx_kind.value:
                continue
            cid = r["category_id"]
            cat = cats.get(cid)
            t = totals.setdefault(cid, CategoryTotal(cid, cat.name if cat else "Kategorisiz",
                                                     cat.color if cat else "#7A7A7A", 0))
            t.amount += -r["amount"] if r["is_refund"] else r["amount"]
            t.count += 1
        return sorted(totals.values(), key=lambda t: t.amount, reverse=True)

    def by_payment_method(self, date_from: date | None, date_to: date | None) -> list[tuple[str, int, int]]:
        """(method name, income, expense) per payment method."""
        with self.db.read() as c:
            methods = {m.id: m.name for m in repo.list_payment_methods(c, include_inactive=True)}
            rows = repo.transactions_for_accounting(c, date_from, date_to)
        acc: dict[str, list[int]] = {}
        for r in rows:
            kind, amount, refund = TxKind(r["kind"]), r["amount"], bool(r["is_refund"])
            if kind not in (TxKind.INCOME, TxKind.EXPENSE):
                continue
            name = methods.get(r["payment_method_id"], "Belirtilmemiş")
            e = acc.setdefault(name, [0, 0])
            e[0] += signed_income(kind, amount, refund)
            e[1] += signed_expense(kind, amount, refund)
        return [(k, v[0], v[1]) for k, v in sorted(acc.items())]

    def export_csv(self, path: Path, date_from: date | None, date_to: date | None) -> int:
        with self.db.read() as c:
            txs = repo.list_transactions(c, TransactionFilter(date_from=date_from, date_to=date_to))
        # utf-8-sig + ';' so Turkish Excel opens it correctly
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Tarih", "Saat", "Tür", "İade", "Tutar", "Kategori", "Ödeme Yöntemi", "Hesap",
                        "Hedef Hesap", "Açıklama", "Not", "Kayıt No"])
            for t in reversed(txs):
                w.writerow([t.occurred_on.strftime("%d.%m.%Y"), t.occurred_time, t.kind.label,
                            "Evet" if t.is_refund else "", format_amount(t.amount, symbol=False),
                            t.category_name, t.payment_method_name, t.account_name, t.to_account_name,
                            t.description, t.note, t.id])
        return len(txs)
