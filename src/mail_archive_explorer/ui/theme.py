"""Thèmes clair / sombre explicites (indépendants du thème du système) et feuille de style."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Couleurs (texte/fond contrôlés : rapports de contraste >= 7:1 pour le texte principal)
LIGHT = dict(window="#f3f4f6", base="#ffffff", alt="#f4f6fa", text="#15181d", muted="#5b6370",
             border="#c9ced6", accent="#1d5fd6", accent_text="#ffffff", header="#e6e9ef",
             notice_bg="#fff1c2", notice_fg="#5a4100", button="#ffffff")
DARK = dict(window="#1e2126", base="#262a31", alt="#2b3039", text="#eef0f3", muted="#a3abb8",
            border="#454c58", accent="#4c8dff", accent_text="#ffffff", header="#323843",
            notice_bg="#4a3d12", notice_fg="#ffe9a8", button="#323843")
THEMES = {"light": LIGHT, "dark": DARK}


def colors(name: str) -> dict:
    return THEMES.get(name, LIGHT)


def current_theme() -> str:
    v = QSettings("MailArchiveExplorer", "ui").value("theme", "light")
    return v if v in THEMES else "light"


def apply_theme(app: QApplication, name: str) -> dict:
    c = colors(name)
    app.setStyle("Fusion")
    pal = QPalette()
    q = QColor
    for role, key in ((QPalette.Window, "window"), (QPalette.Base, "base"), (QPalette.AlternateBase, "alt"),
                      (QPalette.Text, "text"), (QPalette.WindowText, "text"), (QPalette.ButtonText, "text"),
                      (QPalette.Button, "button"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "accent_text"), (QPalette.ToolTipBase, "base"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted"),
                      (QPalette.Link, "accent"), (QPalette.Mid, "border")):
        pal.setColor(role, q(c[key]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, q(c["muted"]))
    app.setPalette(pal)
    QSettings("MailArchiveExplorer", "ui").setValue("theme", name)
    return c


def stylesheet(c: dict) -> str:
    return f"""
QWidget {{ font-size: 13px; }}
QMainWindow, QSplitter {{ background: {c['window']}; }}
QTableView, QTreeWidget, QListWidget, QPlainTextEdit {{
    background: {c['base']}; alternate-background-color: {c['alt']}; color: {c['text']};
    border: 1px solid {c['border']}; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}
QTableView::item {{ padding: 2px 6px; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QHeaderView::section {{ background: {c['header']}; color: {c['text']}; padding: 6px 8px; font-weight: 600;
    border: 0; border-right: 1px solid {c['border']}; border-bottom: 1px solid {c['border']}; }}
QToolBar {{ background: {c['window']}; spacing: 6px; padding: 4px; border: 0; }}
QToolButton {{ color: {c['text']}; padding: 5px 10px; border: 1px solid transparent; border-radius: 6px; }}
QToolButton:hover {{ background: {c['header']}; border: 1px solid {c['border']}; }}
QLineEdit {{ background: {c['base']}; color: {c['text']}; padding: 6px 10px;
    border: 1px solid {c['border']}; border-radius: 6px; }}
QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
QPushButton {{ background: {c['button']}; color: {c['text']}; padding: 5px 12px;
    border: 1px solid {c['border']}; border-radius: 6px; }}
QCheckBox, QLabel {{ color: {c['text']}; }}
QStatusBar {{ background: {c['window']}; color: {c['muted']}; }}
QScrollBar:vertical {{ background: {c['window']}; width: 12px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {c['window']}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QMessageBox, QDialog {{ background: {c['window']}; }}
"""
