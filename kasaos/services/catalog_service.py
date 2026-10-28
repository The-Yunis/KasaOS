"""Categories, payment methods and accounts."""

from __future__ import annotations

import re

from kasaos.core.exceptions import NotFoundError, ValidationError
from kasaos.domain.entities import Account, Category, PaymentMethod
from kasaos.domain.enums import AccountKind, CategoryKind
from kasaos.infrastructure.database import repositories as repo
from kasaos.infrastructure.database.connection import Database

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _name(value: str, what: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"{what} adı boş olamaz.", "name")
    if len(value) > 60:
        raise ValidationError(f"{what} adı en fazla 60 karakter olabilir.", "name")
    return value


class CatalogService:
    def __init__(self, db: Database):
        self.db = db

    # categories
    def categories(self, kind: CategoryKind | None = None, include_inactive: bool = False) -> list[Category]:
        with self.db.read() as c:
            return repo.list_categories(c, kind, include_inactive)

    def add_category(self, name: str, kind: CategoryKind, color: str = "#C9A227") -> Category:
        name = _name(name, "Kategori")
        if not _COLOR.match(color):
            raise ValidationError("Geçersiz renk.", "color")
        with self.db.transaction() as c:
            if repo.find_category(c, name, kind):
                raise ValidationError("Bu isimde bir kategori zaten var.", "name")
            cid = repo.insert_category(c, name, kind, color)
            repo.add_audit(c, "category", str(cid), "create", {"name": name, "kind": kind.value})
            return repo.get_category(c, cid)

    def update_category(self, category_id: int, name: str, color: str, active: bool) -> Category:
        name = _name(name, "Kategori")
        if not _COLOR.match(color):
            raise ValidationError("Geçersiz renk.", "color")
        with self.db.transaction() as c:
            cat = repo.get_category(c, category_id)
            if cat is None:
                raise NotFoundError("Kategori bulunamadı.")
            other = repo.find_category(c, name, cat.kind)
            if other and other.id != category_id:
                raise ValidationError("Bu isimde bir kategori zaten var.", "name")
            repo.update_category(c, category_id, name, color, active)
            repo.add_audit(c, "category", str(category_id), "update",
                           {"name": name, "color": color, "active": active})
            return repo.get_category(c, category_id)

    def delete_category(self, category_id: int) -> None:
        """Delete only unused categories; used ones must be archived (deactivated)."""
        with self.db.transaction() as c:
            if repo.get_category(c, category_id) is None:
                raise NotFoundError("Kategori bulunamadı.")
            used = c.execute("SELECT count(*) FROM transactions WHERE category_id=?", (category_id,)).fetchone()[0]
            if used:
                raise ValidationError(
                    f"Bu kategori {used} işlemde kullanılıyor. Silmek yerine pasif hale getirebilirsiniz.")
            repo.delete_category(c, category_id)
            repo.add_audit(c, "category", str(category_id), "delete")

    def category_usage(self, category_id: int) -> int:
        with self.db.read() as c:
            return repo.category_usage(c, category_id)

    # payment methods
    def payment_methods(self, include_inactive: bool = False) -> list[PaymentMethod]:
        with self.db.read() as c:
            return repo.list_payment_methods(c, include_inactive)

    def add_payment_method(self, name: str, account_id: int) -> PaymentMethod:
        name = _name(name, "Ödeme yöntemi")
        with self.db.transaction() as c:
            if repo.get_account(c, account_id) is None:
                raise ValidationError("Hesap bulunamadı.", "account")
            if c.execute("SELECT 1 FROM payment_methods WHERE lower(name)=lower(?)", (name,)).fetchone():
                raise ValidationError("Bu isimde bir ödeme yöntemi zaten var.", "name")
            mid = repo.insert_payment_method(c, name, account_id)
            repo.add_audit(c, "payment_method", str(mid), "create", {"name": name})
            return repo.get_payment_method(c, mid)

    def update_payment_method(self, method_id: int, name: str, account_id: int, active: bool) -> None:
        name = _name(name, "Ödeme yöntemi")
        with self.db.transaction() as c:
            if repo.get_payment_method(c, method_id) is None:
                raise NotFoundError("Ödeme yöntemi bulunamadı.")
            if repo.get_account(c, account_id) is None:
                raise ValidationError("Hesap bulunamadı.", "account")
            dup = c.execute("SELECT id FROM payment_methods WHERE lower(name)=lower(?) AND id!=?",
                            (name, method_id)).fetchone()
            if dup:
                raise ValidationError("Bu isimde bir ödeme yöntemi zaten var.", "name")
            repo.update_payment_method(c, method_id, name, account_id, active)
            repo.add_audit(c, "payment_method", str(method_id), "update",
                           {"name": name, "account_id": account_id, "active": active})

    # accounts
    def accounts(self, include_inactive: bool = False) -> list[Account]:
        with self.db.read() as c:
            return repo.list_accounts(c, include_inactive)

    def add_account(self, name: str, kind: AccountKind, opening_balance: int = 0) -> Account:
        name = _name(name, "Hesap")
        with self.db.transaction() as c:
            if c.execute("SELECT 1 FROM accounts WHERE lower(name)=lower(?)", (name,)).fetchone():
                raise ValidationError("Bu isimde bir hesap zaten var.", "name")
            aid = repo.insert_account(c, name, kind, opening_balance)
            repo.add_audit(c, "account", str(aid), "create", {"name": name, "opening_balance": opening_balance})
            return repo.get_account(c, aid)

    def update_account(self, account_id: int, name: str, opening_balance: int, active: bool) -> None:
        name = _name(name, "Hesap")
        with self.db.transaction() as c:
            old = repo.get_account(c, account_id)
            if old is None:
                raise NotFoundError("Hesap bulunamadı.")
            dup = c.execute("SELECT id FROM accounts WHERE lower(name)=lower(?) AND id!=?",
                            (name, account_id)).fetchone()
            if dup:
                raise ValidationError("Bu isimde bir hesap zaten var.", "name")
            repo.update_account(c, account_id, name, opening_balance, active)
            repo.add_audit(c, "account", str(account_id), "update",
                           {"before": {"name": old.name, "opening_balance": old.opening_balance},
                            "after": {"name": name, "opening_balance": opening_balance}})
