"""Account balances and daily cash reconciliation (kasa açılış / kapanış)."""

from __future__ import annotations

import logging
from datetime import date

from kasaos.core.exceptions import NotFoundError, ValidationError
from kasaos.domain.entities import CashSession
from kasaos.domain.enums import AccountKind, TxKind
from kasaos.domain.financial_rules import account_effects, expected_closing_cash
from kasaos.infrastructure.database import repositories as repo
from kasaos.infrastructure.database.connection import Database

log = logging.getLogger(__name__)


def _effect_for(row, account_id: int) -> int:
    effects = account_effects(TxKind(row["kind"]), row["amount"], row["account_id"],
                              row["to_account_id"], bool(row["is_refund"]))
    return effects.get(account_id, 0)


class CashService:
    def __init__(self, db: Database):
        self.db = db

    def balance(self, account_id: int, as_of: date | None = None) -> int:
        """Actual account balance (opening balance + every movement up to as_of)."""
        with self.db.read() as c:
            acc = repo.get_account(c, account_id)
            if acc is None:
                raise NotFoundError("Hesap bulunamadı.")
            rows = repo.transactions_for_account(c, account_id, None, as_of)
        return acc.opening_balance + sum(_effect_for(r, account_id) for r in rows)

    def balances(self) -> dict[int, int]:
        with self.db.read() as c:
            accounts = repo.list_accounts(c)
        return {a.id: self.balance(a.id) for a in accounts}

    def cash_account_id(self) -> int | None:
        with self.db.read() as c:
            for a in repo.list_accounts(c):
                if a.kind == AccountKind.CASH:
                    return a.id
        return None

    def day_movements(self, account_id: int, day: date) -> list[int]:
        with self.db.read() as c:
            rows = repo.transactions_for_account(c, account_id, day, day)
        return [_effect_for(r, account_id) for r in rows]

    def expected_cash(self, session: CashSession) -> int:
        return expected_closing_cash(session.opening_amount,
                                     self.day_movements(session.account_id, session.business_date))

    def session(self, account_id: int, day: date) -> CashSession | None:
        with self.db.read() as c:
            return repo.get_cash_session(c, account_id, day)

    def sessions(self, account_id: int, limit: int = 60) -> list[CashSession]:
        with self.db.read() as c:
            return repo.list_cash_sessions(c, account_id, limit)

    def open_session(self, account_id: int, day: date, opening_count: int) -> CashSession:
        if opening_count < 0:
            raise ValidationError("Açılış tutarı negatif olamaz.", "amount")
        with self.db.transaction() as c:
            acc = repo.get_account(c, account_id)
            if acc is None:
                raise NotFoundError("Hesap bulunamadı.")
            if repo.get_cash_session(c, account_id, day):
                raise ValidationError("Bu gün için kasa zaten açılmış.")
            sid = repo.insert_cash_session(c, account_id, day, opening_count)
            repo.add_audit(c, "cash_session", str(sid), "open", {"opening": opening_count, "date": day.isoformat()})
            session = repo.get_cash_session(c, account_id, day)
        log.info("Cash session opened account=%s day=%s", account_id, day)
        return session

    def close_session(self, account_id: int, day: date, counted: int, note: str = "") -> CashSession:
        if counted < 0:
            raise ValidationError("Sayım tutarı negatif olamaz.", "amount")
        session = self.session(account_id, day)
        if session is None:
            raise ValidationError("Önce bu gün için kasayı açınız.")
        if session.is_closed:
            raise ValidationError("Bu günün kasası zaten kapatılmış.")
        expected = self.expected_cash(session)
        with self.db.transaction() as c:
            repo.close_cash_session(c, session.id, counted, expected, (note or "").strip()[:500])
            repo.add_audit(c, "cash_session", str(session.id), "close",
                           {"counted": counted, "expected": expected, "difference": counted - expected})
            closed = repo.get_cash_session(c, account_id, day)
        log.info("Cash session closed account=%s day=%s", account_id, day)
        return closed
