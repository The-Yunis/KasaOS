"""KasaOS-Kurulum.exe — per-user installer (no admin). Stdlib only.

Bundles payload.zip (launcher KasaOS.exe + app/). Installs into
%LOCALAPPDATA%\\Programs\\KasaOS\\versions\\<ver>, makes it current, keeps the
old version as previous, creates shortcuts and starts KasaOS. User data in
%LOCALAPPDATA%\\KasaOS is never touched. Coded by Yunus Açıkgöz
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

from kasaos.updates.install_state import APP_EXE, VERSION_FILE, InstallState, valid_version_name

TITLE = "KasaOS Kurulumu"


def msg(text: str, error: bool = False, ask: bool = False) -> bool:
    flags = (0x10 if error else 0x40) | (0x4 if ask else 0)
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags) in (1, 6)


def app_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KasaOS-app.exe", "/NH"], capture_output=True, text=True,
                         creationflags=0x08000000)
    return "KasaOS-app.exe" in out.stdout


def shortcut(lnk: Path, target: Path) -> None:
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:K_LNK);"
          "$s.TargetPath=$env:K_TGT;$s.WorkingDirectory=$env:K_DIR;"
          "$s.Description='KasaOS - Yeni Nesil İşletme Yönetimi';$s.Save()")
    env = dict(os.environ, K_LNK=str(lnk), K_TGT=str(target), K_DIR=str(target.parent))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env, check=True,
                   creationflags=0x08000000)


def install() -> None:
    payload = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "payload.zip"
    root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "KasaOS"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(payload) as z:
            z.extractall(tmp)
        version = (tmp / "app" / VERSION_FILE).read_text(encoding="ascii").strip()
        if not valid_version_name(version) or not (tmp / "app" / APP_EXE).is_file():
            raise RuntimeError("Kurulum paketi bozuk.")
        if not msg(f"KasaOS {version} bu bilgisayara kurulsun mu?\n\nKonum: {root}\n"
                   "Mevcut verileriniz korunur.", ask=True):
            return
        while app_running():
            if not msg("KasaOS şu anda açık. Lütfen kapatın ve Evet'e basın.", ask=True):
                return
        versions = root / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        target = versions / version
        if not (target / APP_EXE).is_file():
            staging = versions / f".staging-install-{uuid.uuid4().hex[:8]}"
            shutil.copytree(tmp / "app", staging)
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
        shutil.copy2(tmp / "KasaOS.exe", root / "KasaOS.exe")

    st = InstallState.load(root)
    if st.current and st.current != version:
        st.previous = st.current
    st.current = version
    st.pending = None
    st.attempt = None
    st.failed.pop(version, None)
    st.save(root)

    launcher = root / "KasaOS.exe"
    desktop = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    for d in (desktop, programs):
        if d.exists():
            shortcut(d / "KasaOS.lnk", launcher)

    msg(f"KasaOS {version} kuruldu.\nMasaüstündeki KasaOS kısayolu ile açabilirsiniz.\n\nCoded by Yunus Açıkgöz")
    subprocess.Popen([str(launcher)], cwd=str(root), close_fds=True)


def main() -> int:
    try:
        install()
    except Exception as e:  # shown to the user, never silent
        msg(f"Kurulum tamamlanamadı:\n{e}\n\nMevcut KasaOS kurulumunuz ve verileriniz değiştirilmedi.", error=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
