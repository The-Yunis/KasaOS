# Update system

Design goal: **an update can never leave KasaOS unable to start.** A previous updater overwrote the
running executable in place and crashed mid-install; this design never modifies a version that is
in use.

## Install layout

```
%LOCALAPPDATA%\Programs\KasaOS\
  KasaOS.exe            launcher (stable, stdlib only, not replaced by updates)
  install_state.json    current / previous / pending / attempt / failed / last_result
  versions\1.0.0\       KasaOS-app.exe + _internal\ + kasaos-version.txt
  versions\1.0.1\
  run\                  readiness files, launcher lock
  logs\launcher.log
```

User data lives in `%LOCALAPPDATA%\KasaOS` and is never touched by the update process except for the
backup taken before switching.

## Flow

| # | Step | Where |
|---|---|---|
| 1 | List releases (drafts ignored, prereleases only if enabled), semver compare | `UpdateService.check` |
| 2 | Download `kasaos-manifest.json` + `.sig`, **verify Ed25519 signature**, parse, check tag = manifest version, platform, `min_app_version`, schema | `check` |
| 3 | Ask the user (no unattended install is implemented) | `UpdateDialog` |
| 4 | Download artifact to `updates\<v>\*.part`, enforce exact size, verify SHA-256 from the signed manifest | `prepare` |
| 5 | Extract into `versions\.staging-*`: reject absolute paths, `..`, drive letters, symlinks, oversize archives; require `KasaOS-app.exe` and a matching `kasaos-version.txt`; then rename to `versions\<v>` | `stager.stage_artifact` |
| 6 | Verified database backup `pre-update-<v>` | `prepare` |
| 7 | `install_state.pending = <v>` | `launcher_core.request_update` |
| 8 | Start `KasaOS.exe --wait-pid <pid>` and quit | `UpdateService.handoff` |
| 9 | Launcher waits for the app to exit, records `attempt` **before** launching, starts the candidate with `KASAOS_READY_FILE` | `Launcher._trial` |
| 10 | App writes the readiness file after the DB is open/migrated and the main window is shown | `bootstrap._signal_ready` |
| 11 | Ready with matching version within 90 s → `current=<v>`, `previous=<old>`, prune others | launcher |
| 12 | Otherwise: kill candidate, `failed[<v>]=reason`, relaunch previous with a notice | launcher |

Nothing in the active version's folder changes at any step. Success is shown to the user only after
step 11, by the new version.

## Failure handling

- **Candidate crashes, hangs, reports a wrong version or cannot be executed** → rollback in step 12.
- **Launcher dies during a trial** → `attempt` is still set on the next start, so the version is
  marked failed and the old version starts. No restart loop is possible: each pending version gets
  exactly one automatic attempt.
- **Failed versions** are not offered automatically again. The update dialog shows the earlier
  failure reason and allows an explicit retry, which clears the block.
- **Current version folder missing or damaged** → falls back to `previous`, then to the newest
  complete version folder.
- **Corrupt `install_state.json`** → kept aside as `.corrupt-*`, state rebuilt from the folders.
- **Offline, GitHub errors, rate limits, malformed responses** → `check()` returns an error status;
  the app keeps working. Startup checks run 8 s after the window opens, in the background.

## Trust model

- The manifest is signed with an **offline Ed25519 key**. The public key(s) are compiled into the app
  (`kasaos/updates/trust.py`). The signature covers the artifact's SHA-256 and size, so the checksum
  is authenticated even though it is downloaded from the same place as the artifact.
- **Protects against:** tampered or truncated downloads, a compromised GitHub account or release
  page, malicious archives (path traversal, symlinks), installing an artifact for another
  version or platform.
- **Does not protect against:** theft of the private signing key; a compromised developer machine
  at build time; malware already running as the user (it could modify the install folder directly);
  rollback to an *older* signed release is prevented only by the "newer than current" rule.
- Executables are not Authenticode-signed (no certificate is available), so Windows SmartScreen may
  warn on first install.
- **With no trusted key configured, every update is rejected** (secure default).

## Database compatibility

Each manifest declares `schema_version` and `db_compat_floor`. If the floor is above the running
app's schema, an application rollback would not be able to open the migrated DB; the dialog then
warns and requires explicit confirmation, and the `pre-update` backup is the recovery path. Database
schemas are never downgraded automatically.

## Troubleshooting

- `%LOCALAPPDATA%\Programs\KasaOS\logs\launcher.log` — trial, readiness, rollback decisions.
- `%LOCALAPPDATA%\KasaOS\logs\kasaos.log` — app side (download, verification, staging).
- `install_state.json` shows `failed` reasons. To retry a failed version manually, remove it from
  `failed` and set `pending`.
- If KasaOS will not start at all, `versions\<previous>\KasaOS-app.exe` can be run directly; the data
  folder is unaffected.
