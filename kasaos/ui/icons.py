"""Line icons and the KasaOS brand mark, rendered from inline SVG.

Brand mark: a rounded square "kasa" (container) with a drawer slot across the
top and three ascending bars — a till that is also a growth chart.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from kasaos.ui import theme

_PATHS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "income": '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
    "expense": '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
    "cash": '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M8 3h8"/>'
            '<circle cx="12" cy="14.5" r="2"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 7v5l3 2"/>',
    "reports": '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>',
    "categories": '<path d="M4 4h7v7H4z"/><path d="M13 4h7v7h-7z"/><path d="M4 13h7v7H4z"/><circle cx="16.5" cy="16.5" r="3.5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1'
                'a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3'
                'l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1'
                'a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9'
                'a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8'
                'l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "about": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.01"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "transfer": '<path d="M4 8h14"/><path d="M14 4l4 4-4 4"/><path d="M20 16H6"/><path d="M10 12l-4 4 4 4"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
    "backup": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/>'
              '<path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.9-3"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.9 3"/>'
               '<path d="M20 20v-4h-4"/>',
    "empty": '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M9 14.5h6"/>',
}


def _svg(path: str, color: str, stroke: float = 1.7) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{path}</svg>').encode()


def _render(svg: bytes, size: int) -> QPixmap:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(p, QRectF(0, 0, size, size))
    p.end()
    return QPixmap.fromImage(img)


@lru_cache(maxsize=None)
def icon(name: str, color: str = theme.TEXT_MUTED, active: str | None = None) -> QIcon:
    ic = QIcon()
    for s in (16, 20, 24, 32, 48):
        ic.addPixmap(_render(_svg(_PATHS[name], color), s), QIcon.Mode.Normal, QIcon.State.Off)
        if active:
            ic.addPixmap(_render(_svg(_PATHS[name], active), s), QIcon.Mode.Normal, QIcon.State.On)
    return ic


def brand_svg(background: bool = True) -> bytes:
    bg = ('<rect x="0" y="0" width="64" height="64" rx="14" fill="#1A1A1D"/>' if background else "")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  {bg}
  <rect x="11" y="11" width="42" height="42" rx="9" fill="none" stroke="{theme.GOLD}" stroke-width="4"/>
  <rect x="20" y="18.5" width="24" height="3.6" rx="1.8" fill="{theme.GOLD_SOFT}"/>
  <rect x="20" y="36" width="6" height="10" rx="1.6" fill="{theme.GOLD}"/>
  <rect x="29" y="31" width="6" height="15" rx="1.6" fill="{theme.GOLD}"/>
  <rect x="38" y="26" width="6" height="20" rx="1.6" fill="{theme.GOLD_SOFT}"/>
</svg>""".encode()


def brand_pixmap(size: int, background: bool = True) -> QPixmap:
    return _render(brand_svg(background), size)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(brand_pixmap(s))
    return ic
