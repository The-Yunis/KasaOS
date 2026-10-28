# PyInstaller spec for the KasaOS application (onedir: versions/<ver>/KasaOS-app.exe)
# Build via scripts/build.ps1 — Coded by Yunus Açıkgöz
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from kasaos.version import __version__  # noqa: E402

EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.Qt3DCore", "PySide6.QtCharts",
            "PySide6.QtMultimedia", "PySide6.QtNetwork", "PySide6.QtBluetooth", "PySide6.QtPositioning",
            "PySide6.QtSql", "PySide6.QtDesigner", "tkinter", "pytest", "PyInstaller"]

a = Analysis(
    [str(ROOT / "run_kasaos.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "kasaos" / "resources"), "kasaos/resources")],
    hiddenimports=["PySide6.QtSvg"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="KasaOS-app",
    console=False,
    icon=str(ROOT / "kasaos" / "resources" / "icons" / "kasaos.ico"),
    version=str(ROOT / "build" / "version_info_app.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="KasaOS-app", upx=False)
