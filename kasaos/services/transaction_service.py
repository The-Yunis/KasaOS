"""Create, edit and delete transactions. All validation lives here, not in the UI."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta

from kasaos.core.exceptions import NotFoundError, ValidationError
from kasaos.domain.entities import Transaction, TransactionDraft, TransactionFilter
from kasaos.domain.enums import CategoryKind, TxKind
from kasaos.domain.money import MAX_AMOUNT_KURUS
from kasaos.infrastructure.database import repositories as repo
from kasaos.infrastructure.database.connection import Database

log = logging.getLogger(__name__)

MAX_TEXT = 500
MAX_FUTURE_DAYS = 7


class TransactionService:
    def __init__(self, db: Database):
        self.db = db

    # -- validation --------------------------------------------------------------
    def _validate(self, c, d: TransactionDraft) -> TransactionDraft:
        if not isinstance(d.kind, TxKind):
            raise ValidationError("Geçersiz işlem türü.", "kind")
        if not isinstance(d.amount, int) or isinstance(d.amount, bool):
            raise ValidationError("Tutar kuruş cinsinden tam sayı olmalıdır.", "amount")
        if d.amount <= 0:
            raise ValidationError("Tutar sıfırdan büyük olmalıdır.", "amount")
        if d.amount > MAX_AMOUNT_KURUS:
            raise ValidationError("Tutar izin verilen üst sınırı aşıyor.", "amount")
        if not isinstance(d.occurred_on, date):
            raise ValidationError("Geçerli bir tarih seçiniz.", "date")
        if d.occurred_on > date.today() + timedelta(days=MAX_FUTURE_DAYS):
            raise ValidationError("İşlem tarihi çok ileri bir tarih olamaz.", "date")
        if d.occurred_on.year < 2000:
            raise ValidationError("İşlem tarihi geçersiz.", "date")
        d.description = (d.description or "").strip()
        d.note = (d.note or "").strip()
        if len(d.description) > MAX_TEXT or len(d.note) > MAX_TEXT:
            raise ValidationError(f"Açıklama ve not en fazla {MAX_TEXT} karakter olabilir.", "description")
        if d.occurred_time:
            try:
                datetime.strptime(d.occurred_time, "%H:%M")
            except ValueError:
                raise ValidationError("Saat SS:DD biçiminde olmalıdır.", "time") from None

        if d.kind in (TxKind.INCOME, TxKind.EXPENSE):
            if d.category_id is None:
                raise ValidationError("Kategori seçiniz.", "category")
            cat = repo.get_category(c, d.category_id)
            expected = CategoryKind.INCOME if d.kind == TxKind.INCOME else CategoryKind.EXPENSE
            if cat is None or cat.kind != expected:
                raise ValidationError("Seçilen kategori bu işlem türü için geçerli değil.", "category")
            if d.payment_method_id is None:
                raise ValidationError("Ödeme yöntemi seçiniz.", "payment_method")
            pm = repo.get_payment_method(c, d.payment_method_id)
            if pm is None:
                raise ValidationError("Ödeme yöntemi bulunamadı.", "payment_method")
            # Account follows the payment method unless explicitly given.
            if d.account_id is None:
                d.account_id = pm.account_id
            d.to_account_id = None
        else:
            d.category_id = None
            d.is_refund = False
            if d.account_id is None:
                raise ValidationError("Hesap seçiniz.", "account")
            if d.kind == TxKind.TRANSFER:
                if d.to_account_id is None:
                    raise ValidationError("Hedef hesabı seçiniz.", "to_account")
                if d.to_account_id == d.account_id:
                    raise ValidationError("Kaynak ve hedef hesap aynı olamaz.", "to_account")
                if repo.get_account(c, d.to_account_id) is None:
                    raise ValidationError("Hedef hesap bulunamadı.", "to_account")
            else:
                d.to_account_id = None
            if d.payment_method_id is not None and repo.get_payment_method(c, d.payment_method_id) is None:
                raise ValidationError("Ödeme yöntemi bulunamadı.", "payment_method")
        if repo.get_account(c, d.account_id) is None:
            raise ValidationError("Hesap bulunamadı.", "account")
        return d

    # -- commands ----------------------------------------------------------------
    def create(self, draft: TransactionDraft) -> Transaction:
        now = repo.utc_now()
        with self.db.transaction() as c:
            d = self._validate(c, draft)
            t = Transaction(
                id=str(uuid.uuid4()), kind=d.kind, occurred_on=d.occurred_on,
                occurred_time=d.occurred_time or datetime.now().strftime("%H:%M"),
                amount=d.amount, account_id=d.account_id, category_id=d.category_id,
                payment_method_id=d.payment_method_id, to_account_id=d.to_account_id,
                description=d.description, note=d.note, is_refund=d.is_refund,
                created_at=now, updated_at=now)
            repo.insert_transaction(c, t)
            repo.add_audit(c, "transaction", t.id, "create", {"kind": t.kind.value, "amount": t.amount})
            saved = repo.get_transaction(c, t.id)
        log.info("Transaction created id=%s kind=%s", t.id, t.kind.value)
        return saved

    def update(self, tx_id: str, draft: TransactionDraft) -> Transaction:
        with self.db.transaction() as c:
            old = repo.get_transaction(c, tx_id)
            if old is None:
                raise NotFoundError("İşlem bulunamadı veya silinmiş.")
            d = self._validate(c, draft)
            new = Transaction(
                id=tx_id, kind=d.kind, occurred_on=d.occurred_on,
                occurred_time=d.occurred_time or old.occurred_time, amount=d.amount,
                account_id=d.account_id, category_id=d.category_id, payment_method_id=d.payment_method_id,
                to_account_id=d.to_account_id, description=d.description, note=d.note,
                is_refund=d.is_refund, created_at=old.created_at, updated_at=repo.utc_now())
            repo.update_transaction(c, new)
            repo.add_audit(c, "transaction", tx_id, "update",
                           {"before": _audit_view(old), "after": _audit_view(new)})
            saved = repo.get_transaction(c, tx_id)
        log.info("Transaction updated id=%s", tx_id)
        return saved

    def delete(self, tx_id: str) -> None:
        with self.db.transaction() as c:
            old = repo.get_transaction(c, tx_id)
            if old is None:
                raise NotFoundError("İşlem bulunamadı veya zaten silinmiş.")
            repo.soft_delete_transaction(c, tx_id)
            repo.add_audit(c, "transaction", tx_id, "delete", {"before": _audit_view(old)})
        log.info("Transaction deleted id=%s", tx_id)

    # -- queries -----------------------------------------------------------------
    def get(self, tx_id: str) -> Transaction | None:
        with self.db.read() as c:
            return repo.get_transaction(c, tx_id)

    def list(self, f: TransactionFilter) -> list[Transaction]:
        with self.db.read() as c:
            return repo.list_transactions(c, f)

    def history(self, tx_id: str):
        with self.db.read() as c:
            return repo.list_audit(c, "transaction", tx_id)


def _audit_view(t: Transaction) -> dict:
    keys = ("kind", "occurred_on", "occurred_time", "amount", "account_id", "to_account_id",
            "category_id", "payment_method_id", "description", "note", "is_refund")
    data = asdict(t)
    out = {k: data[k] for k in keys}
    out["kind"] = t.kind.value
    out["occurred_on"] = t.occurred_on.isoformat()
    return out
