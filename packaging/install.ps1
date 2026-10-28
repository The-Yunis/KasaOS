# KasaOS per-user installer (no administrator rights needed).
# Installs to %LOCALAPPDATA%\Programs\KasaOS. User data in %LOCALAPPDATA%\KasaOS is never touched.
# Coded by Yunus Açıkgöz
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$version = (Get-Content -Raw -Encoding ascii (Join-Path $src "app\kasaos-version.txt")).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+') { throw "Geçersiz paket sürümü: $version" }
$root = Join-Path $env:LOCALAPPDATA "Programs\KasaOS"
$versions = Join-Path $root "versions"
$target = Join-Path $versions $version

if (Get-Process -Name "KasaOS-app" -ErrorAction SilentlyContinue) {
    throw "KasaOS açık. Lütfen kapatıp kurulumu yeniden çalıştırın."
}
New-Item -ItemType Directory -Force $versions | Out-Null
if (-not (Test-Path (Join-Path $target "KasaOS-app.exe"))) {
    $staging = Join-Path $versions (".staging-install-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    Copy-Item -Recurse (Join-Path $src "app") $staging
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    Move-Item $staging $target
}
Copy-Item -Force (Join-Path $src "KasaOS.exe") (Join-Path $root "KasaOS.exe")

# install_state.json: make this version current, keep the old one as previous.
$statePath = Join-Path $root "install_state.json"
$state = @{ current = $null; previous = $null; pending = $null; attempt = $null; failed = @{}; last_result = $null }
if (Test-Path $statePath) {
    $old = Get-Content -Raw -Encoding utf8 $statePath | ConvertFrom-Json
    if ($old.current -and $old.current -ne $version) { $state.previous = $old.current } else { $state.previous = $old.previous }
}
$state.current = $version
$state | ConvertTo-Json | Set-Content -Encoding utf8 $statePath

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "KasaOS.lnk"))
    $lnk.TargetPath = Join-Path $root "KasaOS.exe"
    $lnk.WorkingDirectory = $root
    $lnk.Description = "KasaOS — Yeni Nesil İşletme Yönetimi"
    $lnk.Save()
}
Write-Host "KasaOS $version kuruldu: $root"
