"""SQL access. Repositories take an open sqlite3 connection supplied by a
service, so the service controls transaction boundaries."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

from kasaos.domain.entities import (Account, AuditEvent, CashSession, Category, PaymentMethod,
                                    Transaction, TransactionFilter)
from kasaos.domain.enums import AccountKind, CategoryKind, TxKind


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- accounts / methods / categories -------------------------------------------------

def list_accounts(c: sqlite3.Connection, include_inactive: bool = False) -> list[Account]:
    sql = "SELECT * FROM accounts" + ("" if include_inactive else " WHERE active=1") + " ORDER BY id"
    return [Account(r["id"], r["name"], AccountKind(r["kind"]), r["opening_balance"], bool(r["active"]))
            for r in c.execute(sql)]


def get_account(c, account_id: int) -> Account | None:
    r = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return Account(r["id"], r["name"], AccountKind(r["kind"]), r["opening_balance"], bool(r["active"])) if r else None


def update_account(c, account_id: int, name: str, opening_balance: int, active: bool) -> None:
    c.execute("UPDATE accounts SET name=?, opening_balance=?, active=? WHERE id=?",
              (name, opening_balance, int(active), account_id))


def insert_account(c, name: str, kind: AccountKind, opening_balance: int) -> int:
    cur = c.execute("INSERT INTO accounts(name, kind, opening_balance, created_at) VALUES (?,?,?,?)",
                    (name, kind.value, opening_balance, utc_now()))
    return cur.lastrowid


def list_payment_methods(c, include_inactive: bool = False) -> list[PaymentMethod]:
    sql = "SELECT * FROM payment_methods" + ("" if include_inactive else " WHERE active=1") + " ORDER BY sort, id"
    return [PaymentMethod(r["id"], r["name"], r["account_id"], bool(r["active"])) for r in c.execute(sql)]


def get_payment_method(c, method_id: int) -> PaymentMethod | None:
    r = c.execute("SELECT * FROM payment_methods WHERE id=?", (method_id,)).fetchone()
    return PaymentMethod(r["id"], r["name"], r["account_id"], bool(r["active"])) if r else None


def insert_payment_method(c, name: str, account_id: int) -> int:
    sort = c.execute("SELECT coalesce(max(sort),0)+1 FROM payment_methods").fetchone()[0]
    return c.execute("INSERT INTO payment_methods(name, account_id, sort) VALUES (?,?,?)",
                     (name, account_id, sort)).lastrowid


def update_payment_method(c, method_id: int, name: str, account_id: int, active: bool) -> None:
    c.execute("UPDATE payment_methods SET name=?, account_id=?, active=? WHERE id=?",
              (name, account_id, int(active), method_id))


def _cat(r) -> Category:
    return Category(r["id"], r["name"], CategoryKind(r["kind"]), r["color"], bool(r["active"]))


def list_categories(c, kind: CategoryKind | None = None, include_inactive: bool = False) -> list[Category]:
    where, params = [], []
    if kind is not None:
        where.append("kind=?")
        params.append(kind.value)
    if not include_inactive:
        where.append("active=1")
    sql = "SELECT * FROM categories" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY sort, name"
    return [_cat(r) for r in c.execute(sql, params)]


def get_category(c, category_id: int) -> Category | None:
    r = c.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    return _cat(r) if r else None


def find_category(c, name: str, kind: CategoryKind) -> Category | None:
    r = c.execute("SELECT * FROM categories WHERE lower(name)=lower(?) AND kind=?", (name, kind.value)).fetchone()
    return _cat(r) if r else None


def insert_category(c, name: str, kind: CategoryKind, color: str) -> int:
    sort = c.execute("SELECT coalesce(max(sort),0)+1 FROM categories WHERE kind=?", (kind.value,)).fetchone()[0]
    return c.execute("INSERT INTO categories(name, kind, color, sort) VALUES (?,?,?,?)",
                     (name, kind.value, color, sort)).lastrowid


def update_category(c, category_id: int, name: str, color: str, active: bool) -> None:
    c.execute("UPDATE categories SET name=?, color=?, active=? WHERE id=?",
              (name, color, int(active), category_id))


def category_usage(c, category_id: int) -> int:
    return c.execute("SELECT count(*) FROM transactions WHERE category_id=? AND deleted_at IS NULL",
                     (category_id,)).fetchone()[0]


def delete_category(c, category_id: int) -> None:
    c.execute("DELETE FROM categories WHERE id=?", (category_id,))


# --- transactions ----------------------------------------------------------------------

_TX_SELECT = """
SELECT t.*, coalesce(cat.name,'') AS category_name, coalesce(pm.name,'') AS payment_method_name,
       a.name AS account_name, coalesce(a2.name,'') AS to_account_name
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN accounts a2 ON a2.id = t.to_account_id
LEFT JOIN categories cat ON cat.id = t.category_id
LEFT JOIN payment_methods pm ON pm.id = t.payment_method_id
"""


def _tx(r) -> Transaction:
    return Transaction(
        id=r["id"], kind=TxKind(r["kind"]), occurred_on=date.fromisoformat(r["occurred_on"]),
        occurred_time=r["occurred_time"], amount=r["amount"], account_id=r["account_id"],
        category_id=r["category_id"], payment_method_id=r["payment_method_id"],
        to_account_id=r["to_account_id"], description=r["description"], note=r["note"],
        is_refund=bool(r["is_refund"]), created_at=r["created_at"], updated_at=r["updated_at"],
        category_name=r["category_name"], payment_method_name=r["payment_method_name"],
        account_name=r["account_name"], to_account_name=r["to_account_name"])


def insert_transaction(c, t: Transaction) -> None:
    c.execute(
        """INSERT INTO transactions(id, kind, occurred_on, occurred_time, amount, account_id, to_account_id,
           category_id, payment_method_id, description, note, is_refund, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (t.id, t.kind.value, t.occurred_on.isoformat(), t.occurred_time, t.amount, t.account_id,
         t.to_account_id, t.category_id, t.payment_method_id, t.description, t.note, int(t.is_refund),
         t.created_at, t.updated_at))


def update_transaction(c, t: Transaction) -> None:
    c.execute(
        """UPDATE transactions SET kind=?, occurred_on=?, occurred_time=?, amount=?, account_id=?,
           to_account_id=?, category_id=?, payment_method_id=?, description=?, note=?, is_refund=?,
           updated_at=? WHERE id=? AND deleted_at IS NULL""",
        (t.kind.value, t.occurred_on.isoformat(), t.occurred_time, t.amount, t.account_id, t.to_account_id,
         t.category_id, t.payment_method_id, t.description, t.note, int(t.is_refund), t.updated_at, t.id))


def soft_delete_transaction(c, tx_id: str) -> int:
    return c.execute("UPDATE transactions SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                     (utc_now(), tx_id)).rowcount


def get_transaction(c, tx_id: str) -> Transaction | None:
    r = c.execute(_TX_SELECT + " WHERE t.id=? AND t.deleted_at IS NULL", (tx_id,)).fetchone()
    return _tx(r) if r else None


def _filter_sql(f: TransactionFilter) -> tuple[str, list]:
    where, params = ["t.deleted_at IS NULL"], []
    if f.date_from:
        where.append("t.occurred_on >= ?")
        params.append(f.date_from.isoformat())
    if f.date_to:
        where.append("t.occurred_on <= ?")
        params.append(f.date_to.isoformat())
    if f.kinds:
        where.append(f"t.kind IN ({','.join('?' * len(f.kinds))})")
        params.extend(k.value for k in f.kinds)
    if f.category_id is not None:
        where.append("t.category_id = ?")
        params.append(f.category_id)
    if f.payment_method_id is not None:
        where.append("t.payment_method_id = ?")
        params.append(f.payment_method_id)
    if f.account_id is not None:
        where.append("(t.account_id = ? OR t.to_account_id = ?)")
        params.extend([f.account_id, f.account_id])
    if f.text:
        where.append("(t.description LIKE ? ESCAPE '\\' OR t.note LIKE ? ESCAPE '\\')")
        like = "%" + f.text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params.extend([like, like])
    return " WHERE " + " AND ".join(where), params


def list_transactions(c, f: TransactionFilter) -> list[Transaction]:
    where, params = _filter_sql(f)
    sql = _TX_SELECT + where + " ORDER BY t.occurred_on DESC, t.occurred_time DESC, t.created_at DESC"
    if f.limit:
        sql += f" LIMIT {int(f.limit)}"
    return [_tx(r) for r in c.execute(sql, params)]


def transactions_for_accounting(c, date_from: date | None, date_to: date | None) -> list[sqlite3.Row]:
    f = TransactionFilter(date_from=date_from, date_to=date_to)
    where, params = _filter_sql(f)
    sql = ("SELECT t.kind, t.amount, t.is_refund, t.occurred_on, t.account_id, t.to_account_id, t.category_id, "
           "t.payment_method_id, a.kind AS account_kind FROM transactions t JOIN accounts a ON a.id=t.account_id")
    return c.execute(sql + where, params).fetchall()


def transactions_for_account(c, account_id: int, date_from: date | None = None,
                             date_to: date | None = None) -> list[sqlite3.Row]:
    f = TransactionFilter(date_from=date_from, date_to=date_to, account_id=account_id)
    where, params = _filter_sql(f)
    return c.execute("SELECT t.* FROM transactions t" + where, params).fetchall()


# --- cash sessions ---------------------------------------------------------------------

def _session(r) -> CashSession:
    return CashSession(r["id"], r["account_id"], date.fromisoformat(r["business_date"]), r["opening_amount"],
                       r["opened_at"], r["counted_amount"], r["expected_amount"], r["closed_at"], r["note"])


def get_cash_session(c, account_id: int, business_date: date) -> CashSession | None:
    r = c.execute("SELECT * FROM cash_sessions WHERE account_id=? AND business_date=?",
                  (account_id, business_date.isoformat())).fetchone()
    return _session(r) if r else None


def list_cash_sessions(c, account_id: int, limit: int = 60) -> list[CashSession]:
    return [_session(r) for r in c.execute(
        "SELECT * FROM cash_sessions WHERE account_id=? ORDER BY business_date DESC LIMIT ?", (account_id, limit))]


def insert_cash_session(c, account_id: int, business_date: date, opening: int) -> int:
    return c.execute("INSERT INTO cash_sessions(account_id, business_date, opening_amount, opened_at) VALUES (?,?,?,?)",
                     (account_id, business_date.isoformat(), opening, utc_now())).lastrowid


def close_cash_session(c, session_id: int, counted: int, expected: int, note: str) -> None:
    c.execute("UPDATE cash_sessions SET counted_amount=?, expected_amount=?, closed_at=?, note=? WHERE id=?",
              (counted, expected, utc_now(), note, session_id))


# --- audit / settings ------------------------------------------------------------------

def add_audit(c, entity: str, entity_id: str, action: str, details: dict | None = None) -> None:
    c.execute("INSERT INTO audit_events(at, entity, entity_id, action, details) VALUES (?,?,?,?,?)",
              (utc_now(), entity, str(entity_id), action, json.dumps(details or {}, ensure_ascii=False)))


def list_audit(c, entity: str | None = None, entity_id: str | None = None, limit: int = 200) -> list[AuditEvent]:
    where, params = [], []
    if entity:
        where.append("entity=?")
        params.append(entity)
    if entity_id:
        where.append("entity_id=?")
        params.append(entity_id)
    sql = "SELECT * FROM audit_events" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [AuditEvent(r["id"], r["at"], r["entity"], r["entity_id"], r["action"], json.loads(r["details"]))
            for r in c.execute(sql, params)]


def get_setting(c, key: str) -> str | None:
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_setting(c, key: str, value: str) -> None:
    c.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, value))
