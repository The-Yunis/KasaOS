# Architecture

```
kasaos/
  version.py            single source of version / schema / platform ids
  config.py             data paths (per-user), install root, env var names
  main.py, bootstrap.py entry point, single-instance lock, startup sequence
  core/                 exceptions, logging + exception hooks, AppContext (service graph)
  domain/               entities, enums, money (kuruş), financial_rules (sign conventions)
  infrastructure/database/  connection (SQLite + lock), migrations, repositories (SQL)
  services/             transaction, catalog, cash, reporting, backup, settings, update
  updates/              manifest + signature, GitHub client, stager, install_state, launcher_core
  ui/                   theme, icons, components, workers, pages/, dialogs/, splash, main_window
launcher/               KasaOS.exe entry (stdlib only)
```

## Layers

- **domain** has no I/O. `financial_rules.py` is the only place that decides how a transaction kind
  affects income, expense and account balances.
- **repositories** contain SQL only; they receive an open connection so the **service** decides the
  transaction boundary (`Database.transaction()` = `BEGIN IMMEDIATE … COMMIT/ROLLBACK`).
- **services** validate every input (amount, date, category kind, payment method, accounts) — the
  UI is not trusted to have done so — and write audit events in the same transaction.
- **ui** never calls SQL directly.

`AppContext.build(paths)` constructs the services explicitly; there is no global mutable state.

## Threading

All database, file and network work runs through `ui/workers.run_async`, which executes on the
global `QThreadPool` and delivers results through a `QObject` living on the GUI thread (queued
signal), so callbacks may touch widgets. Pages snapshot widget values in `params()` on the GUI thread
and pass them to `load()` in the worker. The shared SQLite connection is serialised with an `RLock`.
On shutdown the window waits for running tasks before closing the database.

## Startup

`main.py`: logging → exception hooks → Qt app + stylesheet → single-instance `QLockFile` →
`bootstrap.Startup`. The splash shows real step text ("Veritabanı kontrol ediliyor…") while a
worker opens the DB, runs backup-protected migrations, takes the automatic backup and loads
reference data. On success the main window is shown, then the readiness signal for the launcher is
written. On failure the spinner is replaced by an error state with *Yedekten geri yükle*,
*Günlükler*, *Tekrar dene* and *Kapat* — never an endless spinner, never a silent DB reset.

## Accounting model

| Kind | Income/expense | Balance effect |
|---|---|---|
| income | +income (refund: −) | + account |
| expense | +expense (refund: −) | − account |
| transfer | none | − source, + target |
| owner_withdrawal | none | − account |
| owner_deposit | none | + account |

Payment methods map to accounts (Nakit → Nakit Kasa, Kredi kartı → POS / Kart, …), so "card
collections" and "cash received" are derived from the account kind. Expected closing cash =
counted opening + every signed movement of the cash account that day. "Gelir − gider farkı" is
labelled as a period movement, not an accounting profit.
