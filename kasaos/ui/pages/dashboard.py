"""Genel Bakış — today's position, the month, recent activity."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QGridLayout, QHBoxLayout, QStackedWidget, QTableView, QWidget

from kasaos.domain.entities import TransactionFilter
from kasaos.domain.enums import CategoryKind, TxKind
from kasaos.domain.money import format_amount
from kasaos.ui import theme
from kasaos.ui.components import (BarChart, Card, DonutChart, EmptyState, PageHeader, StatCard, TransactionModel,
                                  button, configure_table, label)
from kasaos.ui.pages.base import Page


class DashboardPage(Page):
    title = "Genel Bakış"

    def __init__(self, window):
        super().__init__(window)
        header = PageHeader("Genel Bakış", "İşletmenizin güncel finansal durumu")
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd.MM.yyyy")
        self.day.setToolTip("Gösterilen gün")
        self.day.dateChanged.connect(lambda _: self.refresh())
        inc = button("+ Gelir Ekle", "Income")
        exp = button("+ Gider Ekle", "Expense")
        inc.setToolTip("Ctrl+G")
        exp.setToolTip("Ctrl+D")
        inc.clicked.connect(lambda: window.open_transaction_dialog(TxKind.INCOME))
        exp.clicked.connect(lambda: window.open_transaction_dialog(TxKind.EXPENSE))
        header.actions.addWidget(self.day)
        header.actions.addWidget(inc)
        header.actions.addWidget(exp)
        self.content.addWidget(header)

        self.stack = QStackedWidget()
        self.empty = EmptyState("Henüz işlem yok",
                                "İlk gelir veya giderinizi ekleyin; özetler, grafikler ve kasa bakiyesi "
                                "otomatik olarak hesaplanacak.", "+ İlk İşlemi Ekle",
                                lambda: window.open_transaction_dialog(TxKind.INCOME))
        self.stack.addWidget(self.empty)
        body = QWidget()
        self.stack.addWidget(body)
        self.content.addWidget(self.stack, 1)
        lay = QGridLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.c_income = StatCard("Günün geliri", theme.INCOME)
        self.c_expense = StatCard("Günün gideri", theme.EXPENSE)
        self.c_net = StatCard("Gelir − gider farkı", hint="Dönem hareketi; resmi kâr değildir.")
        self.c_cash = StatCard("Nakit kasa bakiyesi", theme.GOLD_SOFT, "Güncel gerçek bakiye")
        self.c_card = StatCard("Kart tahsilatı", theme.INFO)
        self.c_m_income = StatCard("Bu ay gelir", theme.INCOME)
        self.c_m_expense = StatCard("Bu ay gider", theme.EXPENSE)
        self.c_m_net = StatCard("Bu ay fark", hint="Gelir − gider; transfer ve sahip çekişleri hariç.")
        for i, c in enumerate([self.c_income, self.c_expense, self.c_net, self.c_cash]):
            lay.addWidget(c, 0, i)
        for i, c in enumerate([self.c_card, self.c_m_income, self.c_m_expense, self.c_m_net]):
            lay.addWidget(c, 1, i)

        chart_card = Card()
        chart_card.body.addWidget(label("Son 14 gün — gelir / gider", "SectionTitle"))
        legend = QHBoxLayout()
        legend.addWidget(label(f'<span style="color:{theme.INCOME}">■</span> Gelir   '
                               f'<span style="color:{theme.EXPENSE}">■</span> Gider', "Faint"))
        legend.addStretch(1)
        chart_card.body.addLayout(legend)
        self.chart = BarChart()
        chart_card.body.addWidget(self.chart)
        lay.addWidget(chart_card, 2, 0, 1, 3)

        donut_card = Card()
        donut_card.body.addWidget(label("Bu ay gider dağılımı", "SectionTitle"))
        self.donut = DonutChart()
        self.donut_empty = label("Bu ay gider kaydı yok.", "Muted")
        donut_card.body.addWidget(self.donut)
        donut_card.body.addWidget(self.donut_empty)
        lay.addWidget(donut_card, 2, 3, 1, 1)

        recent_card = Card()
        row = QHBoxLayout()
        row.addWidget(label("Son işlemler", "SectionTitle"))
        row.addStretch(1)
        all_btn = button("Tümünü gör", "Ghost")
        all_btn.clicked.connect(lambda: window.navigate("history"))
        row.addWidget(all_btn)
        recent_card.body.addLayout(row)
        self.model = TransactionModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        configure_table(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(280)
        self.table.doubleClicked.connect(self._edit)
        recent_card.body.addWidget(self.table)
        lay.addWidget(recent_card, 3, 0, 1, 4)

    def _selected_day(self) -> date:
        q = self.day.date()
        return date(q.year(), q.month(), q.day())

    def _edit(self, index):
        t = self.model.rows[index.row()]
        self.window_.open_transaction_dialog(t.kind, t)

    def params(self):
        return self._selected_day()

    def load(self, day):
        month_start = day.replace(day=1)
        rep, cash = self.ctx.reports, self.ctx.cash
        cash_id = cash.cash_account_id()
        return {
            "any": bool(self.ctx.transactions.list(TransactionFilter(limit=1))),
            "day": rep.summary(day, day),
            "month": rep.summary(month_start, day),
            "cash_balance": cash.balance(cash_id, day) if cash_id else 0,
            "daily": rep.daily(day - timedelta(days=13), day),
            "expense_cats": rep.by_category(CategoryKind.EXPENSE, month_start, day),
            "recent": self.ctx.transactions.list(TransactionFilter(limit=12, date_to=day)),
            "day_label": day.strftime("%d.%m.%Y"),
        }

    def apply(self, d):
        self.stack.setCurrentIndex(1 if d["any"] else 0)
        day, month = d["day"], d["month"]
        self.c_income.set_amount(day.income, f"{day.income_count} işlem")
        self.c_expense.set_amount(day.expense, f"{day.expense_count} işlem")
        self.c_net.set_amount(day.net, signed_color=True)
        self.c_cash.set_amount(d["cash_balance"], f"{d['day_label']} gün sonu itibarıyla")
        self.c_card.set_amount(day.card_income, f"Nakit tahsilat: {format_amount(day.cash_income)}")
        self.c_m_income.set_amount(month.income, f"{month.income_count} işlem")
        self.c_m_expense.set_amount(month.expense, f"{month.expense_count} işlem")
        self.c_m_net.set_amount(month.net, signed_color=True)
        self.chart.set_points(d["daily"])
        self.donut.set_items(d["expense_cats"])
        has = any(c.amount > 0 for c in d["expense_cats"])
        self.donut.setVisible(has)
        self.donut_empty.setVisible(not has)
        self.model.set_rows(d["recent"])
