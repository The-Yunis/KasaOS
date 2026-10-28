"""Render brand assets (PNG sizes + multi-size Windows ICO) from the SVG brand mark.

    python scripts/make_icons.py
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from kasaos.ui.icons import brand_pixmap, brand_svg  # noqa: E402

OUT = ROOT / "kasaos" / "resources" / "icons"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def png_bytes(pm) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """ICO with embedded PNG images (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, data = b"", b""
    offset = 6 + 16 * len(images)
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    path.write_bytes(header + entries + data)


def main():
    QGuiApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kasaos.svg").write_bytes(brand_svg(True))
    (OUT / "kasaos-mark.svg").write_bytes(brand_svg(False))
    images = []
    for s in SIZES:
        png = png_bytes(brand_pixmap(s))
        images.append((s, png))
        (OUT / f"kasaos-{s}.png").write_bytes(png)
    write_ico(OUT / "kasaos.ico", images)
    print("Icons written to", OUT)


if __name__ == "__main__":
    main()
