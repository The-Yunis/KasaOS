# KasaOS

**Yeni Nesil İşletme Yönetimi** — desktop income/expense and cash management for cafes, hookah
lounges, restaurants and other small businesses. Windows, Turkish UI, fully offline for daily use.

Coded by Yunus Açıkgöz

## Features

- Fast income / expense entry (keyboard-first, "Kaydet ve Yeni", duplicate-submit protection)
- Dashboard: today, this month, cash balance, card collections, 14-day chart, expense distribution
- Cash management: account balances, daily opening count, closing reconciliation with discrepancy
- Transfers, owner withdrawals and capital deposits — never counted as income or expense
- History with filters, search, edit, soft delete and a per-record audit trail
- Reports by category and payment method, CSV export (Excel-compatible)
- Verified backups, safe restore (current data is always backed up first)
- Signed, staged, self-rolling-back updates from GitHub Releases

## Development

Requires Python 3.11+ (developed on 3.15) on Windows.

```powershell
python -m pip install -r requirements-dev.txt
python run_kasaos.py                       # start the app
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest tests   # run all tests
```

Data during development goes to `%LOCALAPPDATA%\KasaOS`. Set `KASAOS_HOME` to use a scratch
location instead, e.g. `$env:KASAOS_HOME="$env:TEMP\kasaos-dev"`.

## Packaging

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

This runs the tests, renders the icons, builds `KasaOS-app` (onedir) and the `KasaOS.exe` launcher with
PyInstaller, and writes `release\<version>\`:

| File | Purpose |
|---|---|
| `KasaOS-<v>-windows-x64.zip` | update artifact (application folder) |
| `KasaOS-<v>-windows-x64-kurulum.zip` | first-time install bundle (`install.ps1`, per-user, no admin) |
| `kasaos-manifest.json` | release manifest (sign it before publishing) |
| `SHA256SUMS.txt` | checksums |

Publishing is described in [docs/RELEASE_GUIDE.md](docs/RELEASE_GUIDE.md).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, threading, startup
- [docs/DATABASE.md](docs/DATABASE.md) — schema, money representation, migrations, backups
- [docs/UPDATE_SYSTEM.md](docs/UPDATE_SYSTEM.md) — trust model, staging, readiness, rollback
- [docs/RELEASE_GUIDE.md](docs/RELEASE_GUIDE.md) — versioning, signing, publishing
- [docs/SECURITY.md](docs/SECURITY.md) — security assumptions
- [CHANGELOG.md](CHANGELOG.md)
