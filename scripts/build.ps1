# Build KasaOS for Windows: tests -> icons -> PyInstaller (app + launcher) -> release zip.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1 [-SkipTests]
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (python -c "from kasaos.version import __version__; print(__version__)").Trim()
Write-Host "Building KasaOS $version"

if (-not $SkipTests) {
    $env:QT_QPA_PLATFORM = "offscreen"
    python -m pytest tests
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; not packaging." }
}

python scripts/make_icons.py
python scripts/write_version_info.py

python -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi-app packaging/kasaos_app.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (app) failed" }
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi-launcher packaging/kasaos_launcher.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (launcher) failed" }

# Read the trusted keys / version / update source back out of the built exe (see verify_build.py).
python scripts/verify_build.py
if ($LASTEXITCODE -ne 0) { throw "Built executable failed verification; not packaging." }

# The version marker the stager and launcher verify.
Set-Content -Path "dist/KasaOS-app/kasaos-version.txt" -Value $version -NoNewline -Encoding ascii

python scripts/package_release.py
if ($LASTEXITCODE -ne 0) { throw "Release packaging failed" }

# Single-file installer (KasaOS-Kurulum-<ver>.exe) wrapping launcher + app.
python scripts/make_payload.py
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi-setup packaging/kasaos_setup.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (setup) failed" }
python scripts/finalize_release.py
Write-Host "Done. See release/$version"
