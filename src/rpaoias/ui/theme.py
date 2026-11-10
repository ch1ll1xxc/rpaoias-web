"""Мягкая розовая палитра без баннера, логотипа и внешних ресурсов."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QWidget

CHANGED_BG = "#EEDFF2"
CHANGED_INK = "#633674"
NEXT_BG = "#F8DDE9"
NEXT_INK = "#592D43"

STYLE = """
QMainWindow, QWidget#root { background: #FFF6F8; }
QWidget { color: #4D3443; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: #816173; }
QLabel[role="heading"] { font-size: 21px; font-weight: 600; color: #673C52; }
QLabel[role="section"] { font-weight: 600; color: #81536C; }
QFrame#controls, QFrame#state { background: #FFF9FC; border: 1px solid #EACDDC; border-radius: 11px; }
QLabel#stateText { padding: 3px; }
QLabel[role="flag"] { padding: 5px 8px; border: 1px solid #E6CBD9; border-radius: 7px; background: #FFFAFC; }
QLabel[role="flag"][active="true"] { background: #EBD9EE; border-color: #B58DAF; color: #683C73; font-weight: bold; }
QLabel#error { padding: 7px; border: 1px solid #D992AB; border-radius: 7px; background: #FFE7EF; color: #892B4C; }
QPushButton { background: #FFF9FC; border: 1px solid #D9AFC4; border-radius: 8px; padding: 6px 12px; min-height: 20px; }
QPushButton:hover { background: #F9E3EE; border-color: #B87497; }
QPushButton:pressed, QPushButton:checked { background: #EFD0E1; border-color: #AB5F86; }
QPushButton:focus { border: 2px solid #993D6D; }
QPushButton:disabled { color: #9C8994; background: #F8F1F5; border-color: #E9DAE3; }
QPushButton[role="primary"] { color: #FFFFFF; background: #A64474; border-color: #A64474; font-weight: bold; }
QPushButton[role="primary"]:hover { background: #8C325F; }
QPushButton[role="primary"]:disabled { color: #F8ECF2; background: #C99AB0; border-color: #C99AB0; }
QComboBox, QSpinBox { border: 1px solid #DDBACC; border-radius: 8px; padding: 5px 9px; min-height: 22px; background: #FFFCFE; }
QComboBox:focus, QSpinBox:focus { border-color: #A9577F; }
QComboBox QAbstractItemView { background: #FFFCFE; selection-background-color: #F3D3E3; selection-color: #4D3443; }
QTabWidget::pane { border: 1px solid #E7C9D9; background: #FFFCFD; border-radius: 9px; top: -1px; }
QTabBar::tab { background: #F5E8F0; border: 1px solid #E7C9D9; border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 8px 16px; margin-right: 4px; color: #85596F; }
QTabBar::tab:selected { background: #FFFCFD; border-bottom-color: #FFFCFD; color: #923E68; font-weight: bold; }
QTabBar::tab:hover { background: #FAE8F1; }
QTabWidget#mainTabs > QTabBar::tab { padding: 10px 21px; }
QPlainTextEdit, QTextEdit { background: #FFFCFD; border: 1px solid #E8CBDC; border-radius: 8px; padding: 7px; selection-background-color: #EAC1D6; selection-color: #4D3443; }
QPlainTextEdit:focus { border-color: #B97E9D; }
QTableView { background: #FFFCFD; alternate-background-color: #FFF5F9; border: 1px solid #E8CBDC; border-radius: 7px; gridline-color: #F1E4EC; selection-background-color: #F2D7E5; selection-color: #4D3443; }
QTableView::item { padding: 4px 6px; }
QHeaderView::section { background: #F8ECF3; color: #86536E; border: none; border-bottom: 1px solid #E8CEDD; padding: 6px; font-weight: 600; }
QTableCornerButton::section { background: #F8ECF3; border: none; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: #FAEFF5; width: 11px; margin: 0; border-radius: 5px; }
QScrollBar::handle:vertical { background: #D2A1BC; min-height: 25px; border-radius: 5px; }
QScrollBar:horizontal { background: #FAEFF5; height: 11px; margin: 0; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #D2A1BC; min-width: 25px; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QFrame[role="flow"] { background: #FBEEF5; border: 1px solid #E5BDD2; border-radius: 13px; }
QFrame[role="flow"][center="true"] { background: #F0DFEE; border-color: #C397BA; }
QStatusBar { background: #FFF6F8; color: #805F72; }
QStatusBar::item { border: none; }
QMenuBar { background: #FFF6F8; }
QMenuBar::item:selected { background: #F4DEEA; border-radius: 5px; }
QMenu { background: #FFFCFD; border: 1px solid #D8B3C8; }
QMenu::item:selected { background: #F4DEEA; }
QToolTip { background: #FFFCFD; color: #4D3443; border: 1px solid #C28AA7; padding: 6px; }
"""


def fixed_font() -> QFont:
    available = set(QFontDatabase.families())
    for family in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono"):
        if family in available:
            return QFont(family, 10)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(10)
    return font


def apply_theme(window: QWidget) -> None:
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#FFF6F8"), (QPalette.ColorRole.WindowText, "#4D3443"),
        (QPalette.ColorRole.Base, "#FFFCFD"), (QPalette.ColorRole.AlternateBase, "#FFF5F9"),
        (QPalette.ColorRole.Text, "#4D3443"), (QPalette.ColorRole.Button, "#FFF9FC"),
        (QPalette.ColorRole.ButtonText, "#4D3443"), (QPalette.ColorRole.Highlight, "#F2D7E5"),
        (QPalette.ColorRole.HighlightedText, "#4D3443"), (QPalette.ColorRole.PlaceholderText, "#816173"),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(10)
    window.setFont(font)
    window.setStyleSheet(STYLE)
