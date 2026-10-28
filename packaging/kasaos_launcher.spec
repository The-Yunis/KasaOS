# PyInstaller spec for the stable launcher (KasaOS.exe in the install root). Stdlib only.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

a = Analysis(
    [str(ROOT / "launcher" / "kasaos_launcher.py")],
    pathex=[str(ROOT)],
    excludes=["PySide6", "cryptography", "packaging", "tkinter", "sqlite3"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="KasaOS",
    console=False,
    icon=str(ROOT / "kasaos" / "resources" / "icons" / "kasaos.ico"),
    version=str(ROOT / "build" / "version_info_launcher.txt"),
    upx=False,
)
