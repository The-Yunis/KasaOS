from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kasaos.config import AppPaths  # noqa: E402
from kasaos.core.application_context import AppContext  # noqa: E402
from kasaos.domain.entities import TransactionDraft  # noqa: E402
from kasaos.domain.enums import CategoryKind, TxKind  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    # Guarantee no test ever touches the real %LOCALAPPDATA%\KasaOS.
    monkeypatch.setenv("KASAOS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("KASAOS_INSTALL_ROOT", raising=False)
    monkeypatch.delenv("KASAOS_READY_FILE", raising=False)


@pytest.fixture
def paths(tmp_path) -> AppPaths:
    p = AppPaths(tmp_path / "home")
    p.ensure()
    return p


@pytest.fixture
def ctx(paths):
    c = AppContext.build(paths)
    c.open_database()
    yield c
    c.shutdown()


class Helper:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.methods = {m.name: m for m in ctx.catalog.payment_methods()}
        self.accounts = {a.kind.value: a for a in ctx.catalog.accounts()}

    def cat(self, kind: CategoryKind, name: str | None = None):
        cats = self.ctx.catalog.categories(kind)
        return next(c for c in cats if name is None or c.name == name)

    def income(self, amount: int, day: date | None = None, method="Nakit", refund=False, cat=None):
        return self.ctx.transactions.create(TransactionDraft(
            TxKind.INCOME, day or date.today(), amount,
            category_id=(cat or self.cat(CategoryKind.INCOME)).id,
            payment_method_id=self.methods[method].id, is_refund=refund))

    def expense(self, amount: int, day: date | None = None, method="Nakit", refund=False, cat=None):
        return self.ctx.transactions.create(TransactionDraft(
            TxKind.EXPENSE, day or date.today(), amount,
            category_id=(cat or self.cat(CategoryKind.EXPENSE)).id,
            payment_method_id=self.methods[method].id, is_refund=refund))

    def transfer(self, amount: int, src: str, dst: str, day: date | None = None):
        return self.ctx.transactions.create(TransactionDraft(
            TxKind.TRANSFER, day or date.today(), amount,
            account_id=self.accounts[src].id, to_account_id=self.accounts[dst].id))

    def withdrawal(self, amount: int, src="cash", day: date | None = None):
        return self.ctx.transactions.create(TransactionDraft(
            TxKind.OWNER_WITHDRAWAL, day or date.today(), amount, account_id=self.accounts[src].id))


@pytest.fixture
def h(ctx) -> Helper:
    return Helper(ctx)
