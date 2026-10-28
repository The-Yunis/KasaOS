# Security

## Data

- All business data stays on the local machine (`%LOCALAPPDATA%\KasaOS`). There is no telemetry and
  no network traffic apart from the optional update check to `api.github.com`.
- Logs record events and IDs, not amounts or descriptions, except for audit records that live in the
  database itself.
- The database is not encrypted; it is protected by Windows user-profile permissions. Anyone with
  access to the Windows account can read it.

## Network

- HTTPS only; TLS verification is never disabled; every request has a timeout.
- The release list comes from the configured `owner/repo` only. Asset downloads are restricted to
  GitHub hosts (`github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`).
- No GitHub token is needed or stored.

## Updates

See [UPDATE_SYSTEM.md](UPDATE_SYSTEM.md#trust-model). In short: Ed25519-signed manifest with an
offline key → SHA-256 + size pinned → hardened zip extraction → staged into a separate folder →
readiness-checked switch with automatic rollback. Without a configured public key, updates are
refused.

## Privileges

The app, launcher and installer all run as the normal user; installation is per-user under
`%LOCALAPPDATA%\Programs`. Nothing requests administrator rights. No shell command is built from
untrusted input (the launcher starts executables with argument lists, not a shell).

## Secrets

The signing private key must never be in the repository (`.gitignore` excludes `*.pem`; the
generator refuses to write inside the repo). Rotation: add the new public key to
`TRUSTED_PUBLIC_KEYS`, ship a release signed with the old key, then sign later releases with the new
key and eventually remove the old one.

## Reporting

Please report vulnerabilities privately to the maintainer rather than in a public issue.
