"""Boîte « À propos » : version, licence, dépôt, versions des composants (copiable pour un rapport de bug)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from ...core.about import LICENSE_NAME, REPO_URL, diagnostics
from ...core.i18n import language, tr


def details_text(data_dir: Path | None) -> str:
    import PySide6
    from PySide6.QtCore import qVersion
    d = diagnostics()
    lines = [
        f"Mail Archive Explorer {d['version']}",
        f"Python {d['python']} · PySide6 {PySide6.__version__} · Qt {qVersion()}",
        f"SQLite {d['sqlite']} · pypff {d['pypff']}",
        f"{d['system']} · packaged: {d['frozen']} · language: {language()}",
    ]
    if data_dir:
        lines.append(f"data: {data_dir}")
    return "\n".join(lines)


def build_about(parent, data_dir: Path | None = None) -> QDialog:
    d = diagnostics()
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("À propos"))
    lay = QVBoxLayout(dlg)
    title = QLabel(f"<div style='font-size:20px; font-weight:600'>Mail Archive Explorer</div>"
                   f"<div>{tr('Version')} <b>{d['version']}</b></div>")
    title.setTextFormat(Qt.RichText)
    lay.addWidget(title)
    desc = QLabel(tr("Consultation et recherche locales d'archives PST/OST, OLM, MBOX et EML. "
                     "Aucune donnée ne quitte votre machine."))
    desc.setWordWrap(True)
    lay.addWidget(desc)
    lic = QLabel(tr("Licence : {n}").format(n=LICENSE_NAME))
    lay.addWidget(lic)
    link = QLabel(f"<a href='{REPO_URL}'>{REPO_URL}</a>")
    link.setTextFormat(Qt.RichText)
    link.setOpenExternalLinks(False)
    link.linkActivated.connect(lambda u: u == REPO_URL and QDesktopServices.openUrl(QUrl(u)))
    lay.addWidget(link)
    box = QPlainTextEdit(details_text(data_dir))
    box.setReadOnly(True)
    box.setMaximumHeight(110)
    lay.addWidget(box)
    buttons = QDialogButtonBox()
    copy = buttons.addButton(tr("Copier les détails"), QDialogButtonBox.ActionRole)
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText()))
    close = buttons.addButton(tr("Fermer"), QDialogButtonBox.AcceptRole)
    close.clicked.connect(dlg.accept)
    lay.addWidget(buttons)
    dlg.setMinimumWidth(520)
    return dlg


def show_about(parent, data_dir: Path | None = None) -> None:
    build_about(parent, data_dir).exec()
