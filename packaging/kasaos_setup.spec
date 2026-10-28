# PyInstaller spec for the single-file installer KasaOS-Kurulum-<ver>.exe
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from kasaos.version import __version__  # noqa: E402

a = Analysis(
    [str(ROOT / "installer" / "kasaos_setup.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "build" / "payload.zip"), ".")],
    excludes=["PySide6", "cryptography", "packaging", "tkinter", "sqlite3"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name=f"KasaOS-Kurulum-{__version__}",
    console=False,
    icon=str(ROOT / "kasaos" / "resources" / "icons" / "kasaos.ico"),
    version=str(ROOT / "build" / "version_info_launcher.txt"),
    upx=False,
)
