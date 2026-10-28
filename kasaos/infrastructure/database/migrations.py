"""Versioned, backup-protected schema migrations.

meta.schema_version  — highest migration applied.
meta.compat_floor    — lowest application SCHEMA_VERSION that may still open
                       this database. Additive ("expand") migrations leave it
                       unchanged so an application rollback keeps working.

Procedure (see docs/DATABASE.md):
  1. verify the DB is readable, 2. verified backup, 3. apply all pending
  migrations inside a single transaction, 4. verify integrity + version,
  5. on failure roll back and raise MigrationError naming the backup.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable

from kasaos.core.exceptions import IncompatibleDatabaseError, MigrationError
from kasaos.infrastructure.database.connection import Database, integrity_ok

log = logging.getLogger(__name__)

APP_MARKER = "kasaos"


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]
    # Lowest app schema that can open the DB after this migration.
    compat_floor: int


def _m1_initial(c: sqlite3.Connection) -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
        """CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('cash','bank','pos','other')),
            opening_balance INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL)""",
        """CREATE TABLE payment_methods (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            active INTEGER NOT NULL DEFAULT 1,
            sort INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
            color TEXT NOT NULL DEFAULT '#C9A227',
            active INTEGER NOT NULL DEFAULT 1,
            sort INTEGER NOT NULL DEFAULT 0,
            UNIQUE (name, kind))""",
        """CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN
                ('income','expense','transfer','owner_withdrawal','owner_deposit')),
            occurred_on TEXT NOT NULL,
            occurred_time TEXT NOT NULL DEFAULT '',
            amount INTEGER NOT NULL CHECK (amount > 0),
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            to_account_id INTEGER REFERENCES accounts(id),
            category_id INTEGER REFERENCES categories(id),
            payment_method_id INTEGER REFERENCES payment_methods(id),
            description TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            is_refund INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            CHECK (kind != 'transfer' OR (to_account_id IS NOT NULL AND to_account_id != account_id)))""",
        "CREATE INDEX ix_tx_date ON transactions(occurred_on) WHERE deleted_at IS NULL",
        "CREATE INDEX ix_tx_account ON transactions(account_id)",
        "CREATE INDEX ix_tx_category ON transactions(category_id)",
        """CREATE TABLE cash_sessions (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            business_date TEXT NOT NULL,
            opening_amount INTEGER NOT NULL CHECK (opening_amount >= 0),
            opened_at TEXT NOT NULL,
            counted_amount INTEGER,
            expected_amount INTEGER,
            closed_at TEXT,
            note TEXT NOT NULL DEFAULT '',
            UNIQUE (account_id, business_date))""",
        """CREATE TABLE audit_events (
            id INTEGER PRIMARY KEY,
            at TEXT NOT NULL,
            entity TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}')""",
        "CREATE INDEX ix_audit_entity ON audit_events(entity, entity_id)",
        """CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    ]
    for s in statements:
        c.execute(s)
    _seed_defaults(c)


def _seed_defaults(c: sqlite3.Connection) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    accounts = [("Nakit Kasa", "cash"), ("Banka", "bank"), ("POS / Kart", "pos"), ("Diğer", "other")]
    for name, kind in accounts:
        c.execute("INSERT INTO accounts(name, kind, opening_balance, created_at) VALUES (?,?,0,?)",
                  (name, kind, now))
    acc = {r["kind"]: r["id"] for r in c.execute("SELECT id, kind FROM accounts")}
    methods = [("Nakit", acc["cash"]), ("Kredi kartı", acc["pos"]),
               ("Banka transferi", acc["bank"]), ("Diğer", acc["other"])]
    for i, (name, account_id) in enumerate(methods):
        c.execute("INSERT INTO payment_methods(name, account_id, sort) VALUES (?,?,?)",
                  (name, account_id, i))
    income = [("Satış", "#C9A227"), ("Nargile", "#D4A84B"), ("İçecek", "#B88A2E"),
              ("Yiyecek", "#E0B95C"), ("Diğer Gelir", "#8C7A55")]
    expense = [("Kira", "#C0563F"), ("Personel", "#D9774B"), ("Tedarik / Malzeme", "#B4654A"),
               ("Elektrik / Su / Doğalgaz", "#9E5A6B"), ("Kömür / Tütün", "#7E6A9E"),
               ("Bakım / Onarım", "#5E7E9E"), ("Vergi / Harç", "#6A8E7E"), ("Diğer Gider", "#7A7A7A")]
    for i, (name, color) in enumerate(income):
        c.execute("INSERT INTO categories(name, kind, color, sort) VALUES (?,?,?,?)", (name, "income", color, i))
    for i, (name, color) in enumerate(expense):
        c.execute("INSERT INTO categories(name, kind, color, sort) VALUES (?,?,?,?)", (name, "expense", color, i))


def _m2_employees(c: sqlite3.Connection) -> None:
    # Expand-only: new tables, nothing existing changes, so schema-1 apps can still open the DB.
    c.execute("""CREATE TABLE employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        monthly_salary INTEGER NOT NULL DEFAULT 0 CHECK (monthly_salary >= 0),
        note TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE employee_entries (
        id TEXT PRIMARY KEY,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        kind TEXT NOT NULL CHECK (kind IN ('accrual','payment','repayment','deduction')),
        amount INTEGER NOT NULL CHECK (amount > 0),
        occurred_on TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        transaction_id TEXT REFERENCES transactions(id),
        created_at TEXT NOT NULL,
        deleted_at TEXT)""")
    c.execute("CREATE INDEX ix_emp_entries ON employee_entries(employee_id) WHERE deleted_at IS NULL")
    c.execute("CREATE INDEX ix_emp_entries_tx ON employee_entries(transaction_id)")


def _m3_daily_wage(c: sqlite3.Connection) -> None:
    # Expand-only: defaulted columns, older apps ignore them.
    c.execute("ALTER TABLE employees ADD COLUMN pay_type TEXT NOT NULL DEFAULT 'monthly' "
              "CHECK (pay_type IN ('monthly','daily'))")
    c.execute("ALTER TABLE employees ADD COLUMN daily_wage INTEGER NOT NULL DEFAULT 0 CHECK (daily_wage >= 0)")
    # Marks an accrual as one worked day (Günlük Yoklama), so a day cannot be counted twice.
    c.execute("ALTER TABLE employee_entries ADD COLUMN work_day INTEGER NOT NULL DEFAULT 0")
    c.execute("CREATE INDEX ix_emp_work_day ON employee_entries(occurred_on, employee_id) "
              "WHERE work_day = 1 AND deleted_at IS NULL")


MIGRATIONS: list[Migration] = [
    Migration(1, "İlk şema", _m1_initial, compat_floor=1),
    Migration(2, "Personel takibi", _m2_employees, compat_floor=1),
    Migration(3, "Günlük ücretli personel", _m3_daily_wage, compat_floor=1),
]


def latest_version(migrations: list[Migration] | None = None) -> int:
    return max(m.version for m in (migrations or MIGRATIONS))


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if not has_meta:
        return {}
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def current_schema(conn: sqlite3.Connection) -> int:
    return int(read_meta(conn).get("schema_version", "0"))


def migrate(db: Database, app_schema: int, backup_fn: Callable[[str], object] | None,
            migrations: list[Migration] | None = None) -> int:
    """Bring the database to app_schema. Returns the resulting schema version.

    backup_fn(reason) must create and verify a backup; it is called only when
    there is existing data to protect.
    """
    migrations = sorted(migrations or MIGRATIONS, key=lambda m: m.version)
    conn = db.conn
    meta = read_meta(conn)
    current = int(meta.get("schema_version", "0"))

    if meta and meta.get("app") != APP_MARKER:
        raise IncompatibleDatabaseError("Bu dosya bir KasaOS veritabanı değil.")
    if current == 0:
        tables = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        if tables:
            raise IncompatibleDatabaseError("Veritabanı dosyası tanınmayan tablolar içeriyor.")

    if current > app_schema:
        floor = int(meta.get("compat_floor", str(current)))
        if floor > app_schema:
            raise IncompatibleDatabaseError(
                f"Veritabanı daha yeni bir KasaOS sürümüne ait (şema {current}). "
                f"Bu sürüm şema {app_schema} destekliyor.")
        log.warning("DB schema %s newer than app %s but backward compatible (floor %s)",
                    current, app_schema, floor)
        return current

    pending = [m for m in migrations if current < m.version <= app_schema]
    if not pending:
        return current

    backup_path = None
    if current > 0 and backup_fn is not None:
        backup_path = backup_fn(f"pre-migration-v{current}-to-v{pending[-1].version}")
        log.info("Pre-migration backup created: %s", backup_path)

    log.info("Applying migrations %s", [m.version for m in pending])
    try:
        with db.transaction() as c:
            c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for m in pending:
                log.info("Migration %s: %s", m.version, m.description)
                m.apply(c)
                c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(m.version),))
                c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('compat_floor', ?)", (str(m.compat_floor),))
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('app', ?)", (APP_MARKER,))
    except Exception as e:
        log.exception("Migration failed; transaction rolled back")
        raise MigrationError(
            f"Veritabanı güncellemesi başarısız oldu ve geri alındı: {e}", backup_path) from e

    ok, detail = integrity_ok(conn, quick=False)
    new_version = current_schema(conn)
    if not ok or new_version != pending[-1].version:
        raise MigrationError(f"Güncelleme sonrası doğrulama başarısız: {detail}", backup_path)
    log.info("Database migrated to schema %s", new_version)
    return new_version
