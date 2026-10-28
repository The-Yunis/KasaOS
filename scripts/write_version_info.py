"""Generate Windows VERSIONINFO resources from kasaos/version.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kasaos.version import APP_TAGLINE, DEVELOPER_CREDIT, __version__  # noqa: E402

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}, 0), prodvers=({v}, 0), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041F04B0', [
      StringStruct('ProductName', 'KasaOS'),
      StringStruct('FileDescription', '{desc}'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('ProductVersion', '{ver}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('Comments', '{credit}')])]),
    VarFileInfo([VarStruct('Translation', [0x041F, 1200])])
  ]
)
"""


def main():
    parts = [int(p) for p in __version__.split(".")[:3]]
    v = ", ".join(str(p) for p in parts)
    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    for name, desc in (("KasaOS-app", f"KasaOS — {APP_TAGLINE}"), ("KasaOS", "KasaOS Başlatıcı")):
        text = TEMPLATE.format(v=v, ver=__version__, desc=desc, name=name, credit=DEVELOPER_CREDIT)
        target = out / ("version_info_app.txt" if name == "KasaOS-app" else "version_info_launcher.txt")
        target.write_text(text, encoding="utf-8")
    print("version info written for", __version__)


if __name__ == "__main__":
    main()
