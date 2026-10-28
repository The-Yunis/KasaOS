"""Kasa Yönetimi — account balances, daily opening count and closing reconciliation."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QComboBox, QDateEdit, QGridLayout, QHBoxLayout, QLineEdit, QSizePolicy,
                               QTableWidget, QTableWidgetItem)

from kasaos.core.exceptions import ValidationError
from kasaos.domain.enums import AccountKind, TxKind
from kasaos.domain.money import format_amount, parse_amount
from kasaos.ui import theme
from kasaos.ui.components import Card, PageHeader, StatCard, button, configure_table, confirm, label, show_error
from kasaos.ui.pages.base import Page
from kasaos.ui.workers import run_async


def _parse_count(text: str) -> int:
    """Cash counts may legitimately be zero."""
    if text.strip() in ("0", "0,00", "0,0"):
        return 0
    return parse_amount(text)


class CashPage(Page):
    title = "Kasa Yönetimi"

    def __init__(self, window):
        super().__init__(window)
        header = PageHeader("Kasa Yönetimi", "Hesap bakiyeleri, gün açılışı ve kapanış sayımı")
        for text, kind in (("Transfer", TxKind.TRANSFER), ("Sahip Çekişi", TxKind.OWNER_WITHDRAWAL),
                           ("Sermaye Girişi", TxKind.OWNER_DEPOSIT)):
            b = button(text, icon="transfer" if kind == TxKind.TRANSFER else None)
            b.clicked.connect(lambda _=False, k=kind: window.open_transaction_dialog(k))
            header.actions.addWidget(b)
        self.content.addWidget(header)

        self.balances = QGridLayout()
        self.balances.setSpacing(14)
        self.content.addLayout(self.balances)
        self._balance_cards: dict[int, StatCard] = {}

        sess = Card()
        top = QHBoxLayout()
        top.addWidget(label("Günlük kasa sayımı", "SectionTitle"))
        top.addStretch(1)
        self.account = QComboBox()
        self.account.setMinimumWidth(170)
        self.account.currentIndexChanged.connect(lambda _: self.refresh())
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd.MM.yyyy")
        self.day.dateChanged.connect(lambda _: self.refresh())
        top.addWidget(self.account)
        top.addWidget(self.day)
        sess.body.addLayout(top)
        sess.body.addWidget(label("Beklenen nakit = açılış sayımı + günün nakit girişleri − nakit çıkışları "
                                  "(giderler, transferler, sahip çekişleri dahil).", "Faint", wrap=True))

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self.status = label("", "Muted")
        grid.addWidget(self.status, 0, 0, 1, 4)
        self.s_open = StatCard("Açılış sayımı")
        self.s_expected = StatCard("Beklenen nakit", theme.GOLD_SOFT)
        self.s_counted = StatCard("Sayılan nakit")
        self.s_diff = StatCard("Fark")
        for i, c in enumerate((self.s_open, self.s_expected, self.s_counted, self.s_diff)):
            grid.addWidget(c, 1, i)
        sess.body.addLayout(grid)

        act = QHBoxLayout()
        self.count_edit = QLineEdit()
        self.count_edit.setPlaceholderText("Sayılan tutar, ör. 2.450,00")
        self.count_edit.setMaximumWidth(240)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Kapanış notu (isteğe bağlı)")
        self.open_btn = button("Kasayı Aç", "Primary")
        self.open_btn.clicked.connect(self._open)
        self.close_btn = button("Kasayı Kapat", "Primary")
        self.close_btn.clicked.connect(self._close)
        act.addWidget(self.count_edit)
        act.addWidget(self.note_edit, 1)
        act.addWidget(self.open_btn)
        act.addWidget(self.close_btn)
        act.addStretch(0)
        for b in (self.open_btn, self.close_btn):
            b.setMinimumWidth(150)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sess.body.addLayout(act)
        self.msg = label("", "ErrorText", wrap=True)
        sess.body.addWidget(self.msg)
        self.content.addWidget(sess)

        hist = Card()
        hist.body.addWidget(label("Son kapanışlar", "SectionTitle"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Tarih", "Açılış", "Beklenen", "Sayılan", "Fark"])
        configure_table(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(220)
        hist.body.addWidget(self.table)
        self.content.addWidget(hist)
        self.content.addStretch(1)
        self._accounts_loaded = False

    def params(self):
        q = self.day.date()
        return self.account.currentData(), date(q.year(), q.month(), q.day())

    def load(self, p):
        account_id, day = p
        accounts = self.ctx.catalog.accounts()
        balances = {a.id: self.ctx.cash.balance(a.id) for a in accounts}
        if account_id is None:
            account_id = next((a.id for a in accounts if a.kind == AccountKind.CASH), accounts[0].id if accounts else None)
        session = self.ctx.cash.session(account_id, day) if account_id else None
        expected = self.ctx.cash.expected_cash(session) if session else None
        history = self.ctx.cash.sessions(account_id) if account_id else []
        return accounts, balances, account_id, session, expected, history

    def apply(self, d):
        accounts, balances, account_id, session, expected, history = d
        # balance cards
        for i, a in enumerate(accounts):
            card = self._balance_cards.get(a.id)
            if card is None:
                card = StatCard(a.name, theme.GOLD_SOFT if a.kind == AccountKind.CASH else theme.TEXT,
                                "" if a.kind.label == a.name else a.kind.label)
                self._balance_cards[a.id] = card
                self.balances.addWidget(card, 0, i)
            card.set_amount(balances[a.id])
        # account selector
        self.account.blockSignals(True)
        if self.account.count() != len(accounts):
            self.account.clear()
            for a in accounts:
                self.account.addItem(a.name, a.id)
        self.account.setCurrentIndex(max(0, self.account.findData(account_id)))
        self.account.blockSignals(False)

        self.msg.clear()
        if session is None:
            self.status.setText("Bu gün için kasa henüz açılmadı. Gün başında kasadaki nakdi sayıp girin.")
            for c in (self.s_open, self.s_expected, self.s_counted, self.s_diff):
                c.value.setText("—")
            self.open_btn.setVisible(True)
            self.close_btn.setVisible(False)
            self.count_edit.setPlaceholderText("Açılış sayımı, ör. 500,00")
            self.note_edit.setVisible(False)
        else:
            self.s_open.set_amount(session.opening_amount)
            shown_expected = session.expected_amount if session.is_closed else expected
            self.s_expected.set_amount(shown_expected)
            self.open_btn.setVisible(False)
            if session.is_closed:
                self.status.setText("Kasa kapatıldı.")
                self.s_counted.set_amount(session.counted_amount)
                self.s_diff.set_amount(session.difference, "Fazla" if session.difference > 0 else
                                       "Eksik" if session.difference < 0 else "Denk", signed_color=True)
                self.close_btn.setVisible(False)
                self.count_edit.setVisible(False)
                self.note_edit.setVisible(False)
            else:
                self.status.setText("Kasa açık. Gün sonunda kasadaki nakdi sayıp kapatın.")
                self.s_counted.value.setText("—")
                self.s_diff.value.setText("—")
                self.close_btn.setVisible(True)
                self.count_edit.setVisible(True)
                self.note_edit.setVisible(True)
                self.count_edit.setPlaceholderText("Sayılan tutar, ör. 2.450,00")
        if session is None:
            self.count_edit.setVisible(True)

        self.table.setRowCount(0)
        for s in history:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [s.business_date.strftime("%d.%m.%Y"), format_amount(s.opening_amount),
                    format_amount(s.expected_amount) if s.expected_amount is not None else "Açık",
                    format_amount(s.counted_amount) if s.counted_amount is not None else "—",
                    format_amount(s.difference) if s.difference is not None else "—"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 4 and s.difference:
                    it.setForeground(theme_color(s.difference))
                self.table.setItem(r, c, it)

    def _open(self):
        try:
            amount = _parse_count(self.count_edit.text())
        except ValidationError as e:
            self.msg.setText(str(e))
            return
        account_id, day = self.params()
        self.open_btn.setEnabled(False)
        run_async(lambda: self.ctx.cash.open_session(account_id, day, amount), self._done,
                  self._fail, owner=self)

    def _close(self):
        try:
            counted = _parse_count(self.count_edit.text())
        except ValidationError as e:
            self.msg.setText(str(e))
            return
        if not confirm(self, "Kasayı kapat", f"Sayılan nakit {format_amount(counted)} olarak kaydedilip "
                                             f"gün kapatılsın mı? Bu işlem geri alınamaz."):
            return
        account_id, day = self.params()
        note = self.note_edit.text()
        self.close_btn.setEnabled(False)
        run_async(lambda: self.ctx.cash.close_session(account_id, day, counted, note), self._done,
                  self._fail, owner=self)

    def _done(self, _):
        self.open_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self.count_edit.clear()
        self.note_edit.clear()
        self.window_.notify("Kasa kaydı güncellendi.")
        self.refresh()

    def _fail(self, e):
        self.open_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        if isinstance(e, ValidationError):
            self.msg.setText(str(e))
        else:
            show_error(self, "Kasa işlemi başarısız", e)


def theme_color(v: int):
    from PySide6.QtGui import QColor
    return QColor(theme.INCOME if v > 0 else theme.EXPENSE)
