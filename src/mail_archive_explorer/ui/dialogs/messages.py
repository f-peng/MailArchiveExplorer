"""Boîtes de dialogue en texte BRUT : un nom de fichier ou un message d'erreur venant d'une archive
ne doit jamais être interprété comme du HTML (liens cliquables, balises)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


def _box(parent, icon, title: str, text: str, buttons, default=None) -> int:
    box = QMessageBox(icon, title, text, buttons, parent)
    box.setTextFormat(Qt.PlainText)
    if default is not None:
        box.setDefaultButton(default)
    return box.exec()


def question(parent, title: str, text: str) -> QMessageBox.StandardButton:
    return QMessageBox.StandardButton(_box(parent, QMessageBox.Question, title, text,
                                           QMessageBox.Yes | QMessageBox.No, QMessageBox.No))


def information(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Information, title, text, QMessageBox.Ok)


def warning(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Warning, title, text, QMessageBox.Ok)


def critical(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Critical, title, text, QMessageBox.Ok)
