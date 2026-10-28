# Database

SQLite at `%LOCALAPPDATA%\KasaOS\data\kasaos.db` — outside the install root, so no update ever
writes to it. Logs, backups and update downloads have their own sibling folders.

## Connection settings

`foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL`, `synchronous=FULL`. A `quick_check` runs
on every open; a failing check raises `DatabaseCorruptError` and the file is left untouched.

## Money

All amounts are **integer kuruş** (`amount INTEGER CHECK (amount > 0)`). User input is parsed with
`Decimal` (`domain/money.py`), rejecting more than two decimals, exponents and non-numeric text. No
float is used for any stored value or total. Direction comes from `kind` and `is_refund`, never from
a negative amount.

## Schema (version 2)

| Table | Notes |
|---|---|
| `meta` | `schema_version`, `compat_floor`, `app='kasaos'` |
| `accounts` | cash / bank / pos / other, `opening_balance` |
| `payment_methods` | each bound to an account |
| `categories` | `(name, kind)` unique; archived via `active=0` |
| `transactions` | UUID id, `occurred_on` (local date) + `occurred_time`, soft delete (`deleted_at`), check: transfer needs a different `to_account_id` |
| `cash_sessions` | one per account and business date; stores expected and counted closing amounts |
| `audit_events` | create / update (before + after) / delete per entity |
| `settings` | key/value |
| `employees` *(v2)* | staff; `active=0` keeps history after someone leaves |
| `employee_entries` *(v2)* | accrual / payment / repayment / deduction; `transaction_id` links cash-moving entries to their `transactions` row; soft delete |

Personnel balance = Σ accrual + Σ repayment − Σ payment − Σ deduction (> 0: business owes the employee).
Payments are stored as `Personel` expenses and repayments as expense refunds, created in the same DB
transaction as the entry. Deleting either side deletes both; linked transactions cannot be edited
from the history page.

Timestamps (`created_at`, audit `at`) are UTC ISO-8601; business dates are local calendar dates.

## Migrations

`infrastructure/database/migrations.py` holds an ordered list of `Migration(version, description,
apply, compat_floor)`. On startup:

1. Open and integrity-check the DB.
2. Reject foreign databases (no `meta.app` marker but existing tables).
3. If the DB is newer than the app: open it only when `compat_floor <= app schema`, otherwise
   `IncompatibleDatabaseError`.
4. Otherwise create a verified backup (`pre-migration-vA-to-vB`), apply all pending migrations in
   **one** transaction, then run a full `integrity_check` and confirm the new version.
5. On error roll back and raise `MigrationError` naming the backup; the UI offers restore.

**Rules for new migrations:** prefer expand-only changes (new tables, nullable or defaulted columns)
and keep `compat_floor` unchanged so an application rollback can still open the DB. Raising
`compat_floor` makes a release non-rollback-safe; its manifest then carries the higher
`db_compat_floor`, and the update dialog requires explicit confirmation. Databases are never
downgraded automatically.

Minimum supported: application 1.0.0, schema 1.

## Backups

`BackupService` uses SQLite's online backup API, which is safe in WAL mode, writes to `*.partial`,
verifies the copy (full integrity check + KasaOS marker + schema) and only then renames it to
`*.kasaosbak`. Automatic backups on start keep the newest 30; manual and pre-* backups are never
pruned.

**Restore:** verify the backup → refuse if its schema is newer than the app → back up the current DB
(`pre-restore`), or quarantine-copy it if it cannot be opened → copy the backup next to the live
file → verify again → close → `os.replace`. The original is always recoverable.
