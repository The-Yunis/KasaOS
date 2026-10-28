"""Design tokens and the application stylesheet."""

from __future__ import annotations

BG = "#141416"           # deep charcoal
SURFACE = "#1C1C1F"
SURFACE_2 = "#232327"
SURFACE_3 = "#2B2B30"
BORDER = "#323238"
BORDER_STRONG = "#44444C"
TEXT = "#ECEAE4"
TEXT_MUTED = "#A09D95"
TEXT_FAINT = "#6E6C67"
GOLD = "#C9A227"
GOLD_SOFT = "#E3C565"
GOLD_DIM = "#3A3220"
INCOME = "#6BBF8A"
EXPENSE = "#E07A5F"
WARNING = "#E0B04F"
DANGER = "#E05F5F"
INFO = "#6FA8DC"

FONT = "Segoe UI"
RADIUS = 8
SP = 8  # base spacing unit


def stylesheet() -> str:
    return f"""
* {{ font-family: "{FONT}"; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, #Workspace {{ background: {BG}; }}
QWidget#Page {{ background: {BG}; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 4px 6px; }}

/* sidebar */
#Sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#Wordmark {{ font-size: 17pt; font-weight: 600; letter-spacing: 0.5px; color: {TEXT}; }}
#WordmarkAccent {{ font-size: 17pt; font-weight: 600; color: {GOLD}; }}
#Tagline {{ color: {TEXT_FAINT}; font-size: 8.5pt; }}
#Credit {{ color: {TEXT_FAINT}; font-size: 8pt; }}
QPushButton#NavButton {{
    text-align: left; padding: 9px 14px; border: none; border-radius: {RADIUS}px;
    background: transparent; color: {TEXT_MUTED}; font-size: 10.5pt;
}}
QPushButton#NavButton:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#NavButton:checked {{ background: {GOLD_DIM}; color: {GOLD_SOFT}; font-weight: 600; }}

/* typography */
#PageTitle {{ font-size: 18pt; font-weight: 600; }}
#PageSubtitle {{ color: {TEXT_MUTED}; }}
#SectionTitle {{ font-size: 11.5pt; font-weight: 600; }}
#Muted {{ color: {TEXT_MUTED}; }}
#Faint {{ color: {TEXT_FAINT}; font-size: 9pt; }}
#ErrorText {{ color: {DANGER}; }}

/* cards */
#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#StatLabel {{ color: {TEXT_MUTED}; font-size: 9pt; }}
#StatValue {{ font-size: 17pt; font-weight: 600; }}
#StatHint {{ color: {TEXT_FAINT}; font-size: 8.5pt; }}

/* buttons */
QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS}px;
    padding: 7px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}
QPushButton:focus {{ border-color: {GOLD}; }}
QPushButton#Primary {{ background: {GOLD}; color: #17150F; border: 1px solid {GOLD}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {GOLD_SOFT}; }}
QPushButton#Primary:disabled {{ background: {GOLD_DIM}; color: {TEXT_FAINT}; border-color: {GOLD_DIM}; }}
QPushButton#Income {{ background: #1F3127; border: 1px solid #2F5A3F; color: {INCOME}; font-weight: 600; }}
QPushButton#Income:hover {{ background: #26402F; }}
QPushButton#Expense {{ background: #3A2420; border: 1px solid #6A3A2F; color: {EXPENSE}; font-weight: 600; }}
QPushButton#Expense:hover {{ background: #4A2C26; }}
QPushButton#Danger {{ color: {DANGER}; border-color: #5A2B2B; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {TEXT_MUTED}; }}
QPushButton#Ghost:hover {{ color: {TEXT}; }}

/* inputs */
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QPlainTextEdit, QSpinBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {GOLD}; selection-color: #17150F;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QPlainTextEdit:focus {{ border-color: {GOLD}; }}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{ border-color: {DANGER}; }}
QLineEdit#AmountEdit {{ font-size: 16pt; font-weight: 600; padding: 8px 10px; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER_STRONG};
    selection-background-color: {GOLD_DIM}; selection-color: {GOLD_SOFT}; outline: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER_STRONG};
    background: {SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; }}
QCalendarWidget QWidget {{ alternate-background-color: {SURFACE_2}; }}
QCalendarWidget QAbstractItemView {{ background: {SURFACE}; selection-background-color: {GOLD};
    selection-color: #17150F; }}

/* segmented kind selector */
QPushButton#Segment {{ border-radius: 6px; padding: 6px 12px; background: {SURFACE_2}; color: {TEXT_MUTED}; }}
QPushButton#Segment:checked {{ background: {GOLD_DIM}; color: {GOLD_SOFT}; border-color: {GOLD}; }}

/* tables */
QTableView, QListWidget, QTreeWidget {{
    background: {SURFACE}; alternate-background-color: #1F1F23; border: 1px solid {BORDER};
    border-radius: 8px; gridline-color: transparent; selection-background-color: {GOLD_DIM};
    selection-color: {TEXT}; outline: none;
}}
QTableView::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{ background: {SURFACE}; color: {TEXT_MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 7px 8px; font-size: 9pt; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollArea {{ border: none; background: transparent; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {TEXT_MUTED}; padding: 8px 14px; border: none;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {GOLD_SOFT}; border-bottom-color: {GOLD}; }}
QProgressBar {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 5px; height: 10px;
    text-align: center; color: {TEXT_MUTED}; }}
QProgressBar::chunk {{ background: {GOLD}; border-radius: 4px; }}
QMessageBox {{ background: {SURFACE}; }}

#Toast {{ background: {SURFACE_3}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 10px 16px; }}
#Toast[kind="success"] {{ border-color: #2F5A3F; }}
#Toast[kind="error"] {{ border-color: #6A3A2F; }}
#Banner {{ background: {GOLD_DIM}; border: 1px solid #5A4A22; border-radius: 8px; }}
#BannerDanger {{ background: #3A2420; border: 1px solid #6A3A2F; border-radius: 8px; }}
"""
