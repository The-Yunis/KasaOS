# Build KasaOS for Windows: tests -> icons -> PyInstaller (app + launcher) -> release zip.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1 [-SkipTests]
#
# Uses .venv-build\Scripts\python.exe when present (see docs/RELEASE_GUIDE.md), else `python`.
# Release builds must use a Python that PyInstaller and PySide6 support well: 1.1.1 was built
# with Python 3.15 and failed to start on a customer PC with a DLL error.
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$py = if (Test-Path ".venv-build\Scripts\python.exe") { (Resolve-Path ".venv-build\Scripts\python.exe").Path } else { "python" }
$pyVersion = (& $py -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
$supported = @("3.11", "3.12", "3.13")
if ($supported -notcontains $pyVersion) {
    throw "Python $pyVersion is not a supported release-build Python ($($supported -join ', ')). Create .venv-build with Python 3.13."
}

$version = (& $py -c "from kasaos.version import __version__; print(__version__)").Trim()
Write-Host "Building KasaOS $version with Python $pyVersion ($py)"

if (-not $SkipTests) {
    $env:QT_QPA_PLATFORM = "offscreen"
    & $py -m pytest tests
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; not packaging." }
}

& $py scripts/make_icons.py
& $py scripts/write_version_info.py

& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi-app packaging/kasaos_app.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (app) failed" }
& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi-launcher packaging/kasaos_launcher.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (launcher) failed" }

# Read the trusted keys / version / update source back out of the built exe (see verify_build.py).
& $py scripts/verify_build.py
if ($LASTEXITCODE -ne 0) { throw "Built executable failed verification; not packaging." }

# The version marker the stager and launcher verify.
Set-Content -Path "dist/KasaOS-app/kasaos-version.txt" -Value $version -NoNewline -Encoding ascii

& $py scripts/package_release.py
if ($LASTEXITCODE -ne 0) { throw "Release packaging failed" }

# Single-file installer (KasaOS-Kurulum-<ver>.exe) wrapping launcher + app.
& $py scripts/make_payload.py
& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi-setup packaging/kasaos_setup.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (setup) failed" }
& $py scripts/finalize_release.py
Write-Host "Done. See release/$version"
