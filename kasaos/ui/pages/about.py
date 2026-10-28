"""Hakkında — product identity, version and support information."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from kasaos.ui import icons, theme
from kasaos.ui.components import Card, button, label
from kasaos.ui.pages.base import Page
from kasaos.ui.pages.settings import open_folder
from kasaos.version import APP_TAGLINE, DEVELOPER_CREDIT, SCHEMA_VERSION


class AboutPage(Page):
    title = "Hakkında"

    def __init__(self, window):
        super().__init__(window)
        card = Card(padding=28)
        row = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icons.brand_pixmap(96))
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(6)
        name = label(f'Kasa<span style="color:{theme.GOLD}">OS</span>', "PageTitle")
        name.setStyleSheet("font-size: 24pt;")
        text.addWidget(name)
        text.addWidget(label(APP_TAGLINE, "PageSubtitle"))
        text.addWidget(label(f"Sürüm {window.version_text}  ·  Veritabanı şeması {SCHEMA_VERSION}", "Muted"))
        text.addSpacing(10)
        text.addWidget(label("Kafe, nargile salonu, restoran ve küçük işletmeler için günlük gelir-gider, "
                             "kasa takibi ve raporlama. Verileriniz yalnızca bu bilgisayarda saklanır; "
                             "gelir-gider girişi için internet bağlantısı gerekmez.", "Muted", wrap=True))
        text.addWidget(label("Raporlardaki “gelir − gider farkı” bir dönem hareketidir; resmi muhasebe kârı "
                             "veya vergi beyanı yerine geçmez.", "Faint", wrap=True))
        text.addSpacing(14)
        text.addWidget(label(DEVELOPER_CREDIT, "Muted"))
        row.addLayout(text, 1)
        card.body.addLayout(row)
        self.content.addWidget(card)

        sup = Card()
        sup.body.addWidget(label("Destek bilgileri", "SectionTitle"))
        p = window.ctx.paths
        sup.body.addWidget(label(f"Veri klasörü: {p.root}<br>Günlük dosyası: {p.logs_dir / 'kasaos.log'}",
                                 "Muted", wrap=True))
        r = QHBoxLayout()
        b = button("Günlük klasörünü aç", icon="folder")
        b.clicked.connect(lambda: open_folder(p.logs_dir))
        u = button("Güncellemeleri denetle", icon="refresh")
        u.clicked.connect(lambda: window.check_updates(interactive=True))
        r.addWidget(b)
        r.addWidget(u)
        r.addStretch(1)
        sup.body.addLayout(r)
        self.content.addWidget(sup)
        self.content.addStretch(1)
