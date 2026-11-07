"""Modèle de liste à chargement paresseux (pagination keyset) avec tri côté base."""
from __future__ import annotations

import re
import sqlite3

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from ..core.search import Cursor, Filters, Hit, search

PAGE = 200
# (titre, clé de tri, alignement)
COLUMNS = [
    ("Date (UTC)", "date"),
    ("De", "sender"),
    ("À", "recipients"),
    ("Objet", "subject"),
    ("PJ", "attachments"),
    ("Dossier", "folder"),
    ("Extrait", None),          # visible seulement pendant une recherche
]
COL_DATE, COL_FROM, COL_TO, COL_SUBJECT, COL_ATT, COL_FOLDER, COL_SNIPPET = range(7)
_NAME = re.compile(r'^\s*"?\'?(.*?)"?\'?\s*<[^>]*>\s*$')


def short_name(address: str | None) -> str:
    """« Nom <adr@x> » -> « Nom » ; une adresse seule reste telle quelle."""
    if not address:
        return ""
    m = _NAME.match(address)
    return (m.group(1) or address).strip() if m else address.strip()


def split_recipients(recipients: str | None) -> list[str]:
    if not recipients:
        return []
    return [p.strip() for p in re.split(r",\s*(?=[^,]*(?:<|$))", recipients) if p.strip()]


def short_recipients(recipients: str | None) -> str:
    if not recipients:
        return ""
    parts = split_recipients(recipients)
    first = short_name(parts[0]) if parts else ""
    return first + (f"  +{len(parts) - 1}" if len(parts) > 1 else "")


class MessageListModel(QAbstractTableModel):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.rows: list[Hit] = []
        self.query, self.filters = "", Filters()
        self.sort_key, self.descending = "date", True
        self.cursor: Cursor | None = None
        self.exhausted = True

    def set_search(self, query: str, filters: Filters, sort_key: str | None = None,
                   descending: bool | None = None) -> None:
        """Lève QueryError si la saisie est invalide (le contenu précédent est alors conservé)."""
        key = sort_key or self.sort_key
        desc = self.descending if descending is None else descending
        page = search(self.conn, query, filters, limit=PAGE, sort=key, descending=desc)
        self.beginResetModel()
        self.query, self.filters, self.sort_key, self.descending = query, filters, key, desc
        self.rows = page.hits
        self.cursor = page.next_cursor
        self.exhausted = page.next_cursor is None
        self.endResetModel()

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        return not parent.isValid() and not self.exhausted

    def fetchMore(self, parent=QModelIndex()) -> None:
        page = search(self.conn, self.query, self.filters, after=self.cursor, limit=PAGE,
                      sort=self.sort_key, descending=self.descending)
        if page.hits:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(page.hits) - 1)
            self.rows.extend(page.hits)
            self.endInsertRows()
        self.cursor = page.next_cursor
        self.exhausted = page.next_cursor is None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section][0]
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole and COLUMNS[section][1]:
            return "Cliquer pour trier"

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        h, c = self.rows[index.row()], index.column()
        if role == Qt.DisplayRole:
            if c == COL_DATE:
                return h.sent_at[:16] if h.sent_at else "—"
            if c == COL_FROM:
                return short_name(h.sender) or "(inconnu)"
            if c == COL_TO:
                return short_recipients(h.recipients)
            if c == COL_SUBJECT:
                return h.subject or "(sans objet)"
            if c == COL_ATT:
                return "📎" if h.has_attachments else ""
            if c == COL_FOLDER:
                return h.folder_path.rsplit("/", 1)[-1]
            if c == COL_SNIPPET:
                return " ".join(h.snippet.split())
        elif role == Qt.ToolTipRole:
            if c == COL_FROM:
                return h.sender
            if c == COL_TO:
                return h.recipients
            if c == COL_FOLDER:
                return f"{h.archive_path}\n{h.folder_path}"
            if c == COL_SUBJECT:
                return h.subject
        elif role == Qt.ForegroundRole and (c == COL_DATE and not h.sent_at or c == COL_SUBJECT and not h.subject
                                            or c == COL_FROM and not h.sender):
            return QColor(130, 130, 130)
        elif role == Qt.TextAlignmentRole and c == COL_ATT:
            return int(Qt.AlignCenter)
        elif role == Qt.UserRole:
            return h.id
