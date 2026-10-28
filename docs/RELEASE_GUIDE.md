# Release guide

Releases are published manually by the maintainer. CI builds and tests but never signs or publishes.

## One-time setup

1. Generate the signing key **outside the repository** and keep it offline and backed up:
   ```powershell
   python scripts/generate_signing_key.py        # writes %USERPROFILE%\.kasaos-signing\private.pem
   ```
2. Paste the printed public key into `kasaos/updates/trust.py` (`TRUSTED_PUBLIC_KEYS`) and commit it.
   Only builds containing the key can verify updates.
3. Set the default update source in `kasaos/config.py` (`DEFAULT_GITHUB_OWNER`,
   `DEFAULT_GITHUB_REPO`), or set it per installation in *Ayarlar → Güncelleme*.

## Each release

1. Bump `__version__` in `kasaos/version.py` (semantic versioning). If the release adds a migration,
   bump `SCHEMA_VERSION` and add the migration (see DATABASE.md).
2. Add a `## [x.y.z]` section to `CHANGELOG.md`; it becomes the release notes in the manifest.
3. Set `MIN_APP_VERSION` in `scripts/package_release.py` if older versions must not jump directly.
4. Build (runs the full test suite first and stops on failure):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\build.ps1
   ```
5. Sign the manifest:
   ```powershell
   python scripts/sign_manifest.py release\x.y.z\kasaos-manifest.json --key $env:USERPROFILE\.kasaos-signing\private.pem
   ```
   The script verifies the signature against `trust.py` before writing `kasaos-manifest.json.sig`.
6. Upgrade test on a clean Windows user or VM: install the previous version's `-kurulum.zip`, enter
   data, publish the new release as a **prerelease** on a test repository, enable prereleases in
   Settings, update, and confirm the data and the "güncellendi" notice.
7. Create a GitHub release with tag `vx.y.z` and upload:
   - `KasaOS-x.y.z-windows-x64.zip`
   - `KasaOS-x.y.z-windows-x64-kurulum.zip`
   - `kasaos-manifest.json`
   - `kasaos-manifest.json.sig`
   - `SHA256SUMS.txt`

   Asset names must match exactly; the tag must equal the manifest version.

## Rolling back a bad release

Installed clients roll back on their own if the new version fails to start. If a release starts but
is faulty, publish a fixed higher version. Do not delete releases that clients may already have
staged; edit them as prerelease only if you need to stop further downloads.
