"""Raporlar — period totals, category and payment-method breakdowns, CSV export."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QTableWidget, QTableWidgetItem

from kasaos.domain.entities import TransactionFilter
from kasaos.domain.enums import CategoryKind
from kasaos.domain.money import format_amount
from kasaos.ui import theme
from kasaos.ui.components import BarChart, Card, PageHeader, StatCard, button, configure_table, label, show_error
from kasaos.ui.pages.base import Page
from kasaos.ui.pages.transactions import DateRangeBar
from kasaos.ui.workers import run_async


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    configure_table(t)
    t.horizontalHeader().setStretchLastSection(True)
    t.setMinimumHeight(220)
    return t


def _fill(table, rows):
    table.setRowCount(0)
    for row in rows:
        r = table.rowCount()
        table.insertRow(r)
        for c, v in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(v))


class ReportsPage(Page):
    title = "Raporlar"

    def __init__(self, window):
        super().__init__(window)
        header = PageHeader("Raporlar", "Seçilen dönem için gelir-gider özeti")
        self.export_btn = button("CSV olarak dışa aktar", icon="download")
        self.export_btn.clicked.connect(self._export)
        header.actions.addWidget(self.export_btn)
        self.content.addWidget(header)
        bar = QHBoxLayout()
        self.range = DateRangeBar(lambda: self.refresh() if hasattr(self, "chart") else None, "Bu ay")
        bar.addLayout(self.range)
        bar.addStretch(1)
        self.content.addLayout(bar)

        cards = QGridLayout()
        cards.setSpacing(14)
        self.c_inc = StatCard("Toplam gelir", theme.INCOME)
        self.c_exp = StatCard("Toplam gider", theme.EXPENSE)
        self.c_net = StatCard("Gelir − gider farkı", hint="Resmi muhasebe kârı değildir; stok maliyeti ve "
                                                          "vergiler dahil değildir.")
        self.c_card = StatCard("Kart tahsilatı", theme.INFO)
        self.c_cash = StatCard("Nakit tahsilat", theme.GOLD_SOFT)
        self.c_owner = StatCard("Sahip çekişleri", hint="Gider sayılmaz")
        self.c_dep = StatCard("Sermaye girişleri", hint="Gelir sayılmaz")
        self.c_tr = StatCard("Hesaplar arası transfer", hint="Gelir/gider sayılmaz")
        for i, c in enumerate((self.c_inc, self.c_exp, self.c_net, self.c_card)):
            cards.addWidget(c, 0, i)
        for i, c in enumerate((self.c_cash, self.c_owner, self.c_dep, self.c_tr)):
            cards.addWidget(c, 1, i)
        self.content.addLayout(cards)

        chart = Card()
        chart.body.addWidget(label("Günlük gelir / gider", "SectionTitle"))
        self.chart = BarChart()
        chart.body.addWidget(self.chart)
        self.content.addWidget(chart)

        grid = QGridLayout()
        grid.setSpacing(14)
        ci = Card()
        ci.body.addWidget(label("Gelir kategorileri", "SectionTitle"))
        self.t_inc = _table(["Kategori", "İşlem", "Tutar", "Pay"])
        ci.body.addWidget(self.t_inc)
        ce = Card()
        ce.body.addWidget(label("Gider kategorileri", "SectionTitle"))
        self.t_exp = _table(["Kategori", "İşlem", "Tutar", "Pay"])
        ce.body.addWidget(self.t_exp)
        cp = Card()
        cp.body.addWidget(label("Ödeme yöntemleri", "SectionTitle"))
        self.t_pm = _table(["Yöntem", "Gelir", "Gider"])
        cp.body.addWidget(self.t_pm)
        grid.addWidget(ci, 0, 0)
        grid.addWidget(ce, 0, 1)
        grid.addWidget(cp, 1, 0, 1, 2)
        self.content.addLayout(grid)

    def params(self):
        return self.range.range()

    def load(self, rng):
        a, b = rng
        rep = self.ctx.reports
        if a is None:
            oldest = self.ctx.transactions.list(TransactionFilter())
            a = min((t.occurred_on for t in oldest), default=date.today())
            b = date.today()
        span_from = a if (b - a).days <= 92 else b.replace(day=1)
        return {"summary": rep.summary(a, b), "daily": rep.daily(span_from, b),
                "inc": rep.by_category(CategoryKind.INCOME, a, b), "exp": rep.by_category(CategoryKind.EXPENSE, a, b),
                "pm": rep.by_payment_method(a, b)}

    def apply(self, d):
        s = d["summary"]
        self.c_inc.set_amount(s.income, f"{s.income_count} işlem")
        self.c_exp.set_amount(s.expense, f"{s.expense_count} işlem")
        self.c_net.set_amount(s.net, signed_color=True)
        self.c_card.set_amount(s.card_income)
        self.c_cash.set_amount(s.cash_income)
        self.c_owner.set_amount(s.owner_withdrawals)
        self.c_dep.set_amount(s.owner_deposits)
        self.c_tr.set_amount(s.transfers)
        self.chart.set_points(d["daily"])
        for table, items in ((self.t_inc, d["inc"]), (self.t_exp, d["exp"])):
            total = sum(i.amount for i in items) or 1
            _fill(table, [(i.name, str(i.count), format_amount(i.amount), f"%{i.amount * 100 / total:.1f}".replace(".", ","))
                          for i in items])
        _fill(self.t_pm, [(n, format_amount(i), format_amount(e)) for n, i, e in d["pm"]])

    def _export(self):
        a, b = self.range.range()
        name = f"KasaOS-rapor-{(a or date.today()).isoformat()}_{(b or date.today()).isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Raporu kaydet", name, "CSV (*.csv)")
        if not path:
            return
        self.export_btn.setEnabled(False)
        from pathlib import Path
        run_async(lambda: self.ctx.reports.export_csv(Path(path), a, b),
                  lambda n: (self.export_btn.setEnabled(True), self.window_.notify(f"{n} kayıt dışa aktarıldı.")),
                  lambda e: (self.export_btn.setEnabled(True), show_error(self, "Dışa aktarılamadı", e)), owner=self)
