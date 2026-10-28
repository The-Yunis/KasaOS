"""Reusable widgets of the KasaOS design system."""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import (QAbstractTableModel, QEasingCurve, QModelIndex, QPropertyAnimation, QRectF, Qt,
                            QTimer, Property)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from kasaos.domain.entities import Transaction
from kasaos.domain.enums import TxKind
from kasaos.domain.money import format_amount
from kasaos.ui import icons, theme

log = logging.getLogger(__name__)


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if obj:
        lbl.setObjectName(obj)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str, obj: str | None = None, icon: str | None = None, icon_color: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if icon:
        b.setIcon(icons.icon(icon, icon_color or theme.TEXT_MUTED))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Card(QFrame):
    def __init__(self, parent=None, padding: int = 16):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(8)


class StatCard(Card):
    def __init__(self, title: str, accent: str = theme.TEXT, hint: str = ""):
        super().__init__()
        self.title = label(title, "StatLabel")
        self.value = label("—", "StatValue")
        self.value.setStyleSheet(f"color: {accent};")
        self.hint = label(hint, "StatHint", wrap=True)
        self.body.addWidget(self.title)
        self.body.addWidget(self.value)
        self.body.addWidget(self.hint)
        # Preferred height lets the grid give every card in a row the same height.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.body.addStretch(1)
        self.setMinimumWidth(170)

    def set_amount(self, kurus: int, hint: str | None = None, signed_color: bool = False):
        self.value.setText(format_amount(kurus))
        if signed_color:
            self.value.setStyleSheet(f"color: {theme.INCOME if kurus >= 0 else theme.EXPENSE};")
        if hint is not None:
            self.hint.setText(hint)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, "PageTitle"))
        if subtitle:
            text.addWidget(label(subtitle, "PageSubtitle"))
        lay.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)


class EmptyState(QWidget):
    def __init__(self, title: str, text: str, action_text: str | None = None, on_action=None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.icon("empty", theme.TEXT_FAINT).pixmap(48, 48))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = label(title, "SectionTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        d = label(text, "Muted", wrap=True)
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setMaximumWidth(420)
        lay.addWidget(d, 0, Qt.AlignmentFlag.AlignCenter)
        if action_text and on_action:
            b = button(action_text, "Primary")
            b.clicked.connect(on_action)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignCenter)


class Spinner(QWidget):
    """Arc spinner animated by QPropertyAnimation (no sleeps, no busy loops)."""

    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.setFixedSize(size, size)
        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(1100)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    def _get_angle(self):
        return self._angle

    def _set_angle(self, v):
        self._angle = v
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    def start(self):
        self._anim.start()
        self.show()

    def stop(self):
        self._anim.stop()
        self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 3.0
        r = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        p.setPen(QPen(QColor(theme.BORDER_STRONG), w))
        p.drawEllipse(r)
        pen = QPen(QColor(theme.GOLD), w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, int(-self._angle * 16), 100 * 16)


class Toast(QLabel):
    """Transient, non-blocking feedback shown at the bottom of the workspace."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self._fade)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)

    def show_message(self, text: str, kind: str = "success", ms: int = 3200):
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        color = {"success": theme.INCOME, "error": theme.DANGER}.get(kind, theme.TEXT)
        self.setText(f'<span style="color:{color}">●</span>&nbsp;&nbsp;{text}')
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 28)
        self._anim.stop()
        self._fx.setOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _fade(self):
        self._anim.setDuration(350)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.hide)
        self._anim.start()


class BarChart(QWidget):
    """Daily income/expense bars."""

    def __init__(self):
        super().__init__()
        self.points = []
        self.setMinimumHeight(220)

    def set_points(self, points):
        self.points = points
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(56, 12, -8, -26)
        if not self.points or rect.width() < 40:
            return
        peak = max([max(pt.income, pt.expense) for pt in self.points] + [1])
        p.setFont(QFont(theme.FONT, 8))
        # grid
        for i in range(5):
            y = rect.bottom() - rect.height() * i / 4
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.drawLine(rect.left(), int(y), rect.right(), int(y))
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(QRectF(0, y - 8, 52, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       _compact(peak * i // 4))
        n = len(self.points)
        slot = rect.width() / n
        bw = max(2.0, min(14.0, slot * 0.32))
        label_every = max(1, n // 10)
        for i, pt in enumerate(self.points):
            x = rect.left() + slot * i + slot / 2
            for value, color, dx in ((max(pt.income, 0), theme.INCOME, -bw - 1), (max(pt.expense, 0), theme.EXPENSE, 1)):
                h = rect.height() * value / peak
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(color)))
                p.drawRoundedRect(QRectF(x + dx, rect.bottom() - h, bw, h), 2, 2)
            if i % label_every == 0:
                p.setPen(QColor(theme.TEXT_FAINT))
                p.drawText(QRectF(x - 24, rect.bottom() + 6, 48, 16), Qt.AlignmentFlag.AlignCenter,
                           pt.day.strftime("%d.%m"))


class DonutChart(QWidget):
    def __init__(self):
        super().__init__()
        self.items = []
        self.setMinimumHeight(200)

    def set_items(self, items):
        self.items = [i for i in items if i.amount > 0]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(i.amount for i in self.items)
        side = min(self.height() - 10, self.width() * 0.38)
        ring = QRectF(10, (self.height() - side) / 2, side, side)
        if total <= 0:
            p.setPen(QPen(QColor(theme.BORDER_STRONG), 16))
            p.drawEllipse(ring.adjusted(8, 8, -8, -8))
            return
        start = 90 * 16
        pen_w = max(10, side * 0.14)
        inner = ring.adjusted(pen_w / 2, pen_w / 2, -pen_w / 2, -pen_w / 2)
        for it in self.items:
            span = -int(round(360 * 16 * it.amount / total))
            pen = QPen(QColor(it.color), pen_w)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(inner, start, span)
            start += span
        # legend
        p.setFont(QFont(theme.FONT, 9))
        x = ring.right() + 18
        y = ring.top() + 4
        for it in self.items[:7]:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(it.color))
            p.drawRoundedRect(QRectF(x, y + 4, 10, 10), 2, 2)
            p.setPen(QColor(theme.TEXT))
            pct = it.amount * 100 / total
            text = p.fontMetrics().elidedText(it.name, Qt.TextElideMode.ElideRight, int(self.width() - x - 56))
            p.drawText(QRectF(x + 16, y, self.width() - x - 16, 18), Qt.AlignmentFlag.AlignVCenter, text)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(QRectF(x, y, self.width() - x - 6, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"%{pct:.0f}")
            y += 24


def _compact(kurus: int) -> str:
    lira = kurus / 100
    if lira >= 1_000_000:
        return f"{lira / 1_000_000:.1f}M".replace(".", ",")
    if lira >= 1000:
        return f"{lira / 1000:.0f}B"
    return f"{lira:.0f}"


class TransactionModel(QAbstractTableModel):
    HEADERS = ["Tarih", "Saat", "Tür", "Kategori / Hesap", "Ödeme", "Açıklama", "Tutar"]

    def __init__(self):
        super().__init__()
        self.rows: list[Transaction] = []

    def set_rows(self, rows: list[Transaction]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole and section == 6:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        t = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return t.occurred_on.strftime("%d.%m.%Y")
            if col == 1:
                return t.occurred_time
            if col == 2:
                return t.kind.label + (" (İade)" if t.is_refund else "")
            if col == 3:
                if t.kind == TxKind.TRANSFER:
                    return f"{t.account_name} → {t.to_account_name}"
                return t.category_name or t.account_name
            if col == 4:
                return t.payment_method_name or t.account_name
            if col == 5:
                return t.description + (f" — {t.note}" if t.note else "")
            if col == 6:
                return ("−" if _outflow(t) else "+" if _inflow(t) else "") + format_amount(t.amount)
        if role == Qt.ItemDataRole.ForegroundRole and col in (2, 6):
            if _inflow(t):
                return QColor(theme.INCOME)
            if _outflow(t):
                return QColor(theme.EXPENSE)
            return QColor(theme.INFO)
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 6:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and col == 5 and (t.description or t.note):
            return t.description + ("\n" + t.note if t.note else "")
        if role == Qt.ItemDataRole.UserRole:
            return t
        return None


def _inflow(t: Transaction) -> bool:
    return (t.kind == TxKind.INCOME and not t.is_refund) or (t.kind == TxKind.EXPENSE and t.is_refund) \
        or t.kind == TxKind.OWNER_DEPOSIT


def _outflow(t: Transaction) -> bool:
    return (t.kind == TxKind.EXPENSE and not t.is_refund) or (t.kind == TxKind.INCOME and t.is_refund) \
        or t.kind == TxKind.OWNER_WITHDRAWAL


def configure_table(view):
    from PySide6.QtWidgets import QAbstractItemView, QHeaderView
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(34)
    view.setShowGrid(False)
    view.setWordWrap(False)
    hh = view.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    hh.setStretchLastSection(False)


def confirm(parent, title: str, text: str, ok_text: str = "Evet", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    yes = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
    if danger:
        yes.setObjectName("Danger")
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes


def show_error(parent, title: str, exc: BaseException | str):
    from kasaos.core.exceptions import KasaOSError
    if isinstance(exc, KasaOSError) or isinstance(exc, str):
        text = str(exc)
        detail = None
    else:
        text = "Beklenmeyen bir hata oluştu. İşlem tamamlanmadı."
        detail = f"{type(exc).__name__}: {exc}\n\nAyrıntılar günlük dosyasına kaydedildi."
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setDetailedText(detail)
    box.exec()


def today() -> date:
    return date.today()
