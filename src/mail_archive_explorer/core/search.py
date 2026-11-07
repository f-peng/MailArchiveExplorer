"""Recherche plein texte FTS5 + filtres, pagination keyset, multi-archives."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from .query_parser import ParsedQuery, QueryError, parse_query


@dataclass
class Filters:
    archive_ids: Optional[list[int]] = None
    folder_id: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    has_attachments: Optional[bool] = None


SORTS = {  # clé -> expression SQL triée (texte insensible à la casse)
    "date": "m.sent_at",
    "sender": "COALESCE(m.sender,'') COLLATE NOCASE",
    "recipients": "COALESCE(m.recipients,'') COLLATE NOCASE",
    "subject": "COALESCE(m.subject,'') COLLATE NOCASE",
    "folder": "fo.path COLLATE NOCASE",
    "attachments": "m.has_attachments",
}


@dataclass(frozen=True)
class Cursor:
    """Position keyset : valeur de la colonne de tri (None possible pour la date) + id."""
    value: object
    id: int


@dataclass
class Hit:
    id: int
    sent_at: str | None
    sender: str | None
    recipients: str | None
    subject: str | None
    archive_id: int
    archive_path: str
    folder_path: str
    has_attachments: bool
    snippet: str


@dataclass
class Page:
    hits: list[Hit]
    next_cursor: Cursor | None


def search(conn: sqlite3.Connection, query: str = "", filters: Filters | None = None,
           after: Cursor | None = None, limit: int = 100,
           sort: str = "date", descending: bool = True) -> Page:
    """Requêtes paramétrées uniquement. Lève QueryError si la saisie est invalide."""
    if sort not in SORTS:
        raise ValueError(f"Tri inconnu : {sort!r}")
    f = filters or Filters()
    pq: ParsedQuery = parse_query(query or "")
    where, params = [], []
    joins = ""
    if pq.fts:
        joins = "JOIN messages_fts ON messages_fts.rowid = m.id"
        where.append("messages_fts MATCH ?")
        params.append(pq.fts)
        snippet = "snippet(messages_fts, 3, '[', ']', '…', 14)"
    else:
        snippet = "m.excerpt"

    date_from = f.date_from or pq.date_from
    date_to = f.date_to or pq.date_to
    if date_from:
        where.append("m.sent_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("m.sent_at < ?")
        params.append(date_to + " 23:59:59.999" if len(date_to) == 10 else date_to)
    if f.has_attachments or pq.has_attachments:
        where.append("m.has_attachments = 1")
    if f.archive_ids:
        where.append(f"m.archive_id IN ({','.join('?' * len(f.archive_ids))})")
        params.extend(f.archive_ids)
    if f.folder_id is not None:
        where.append("m.folder_id = ?")
        params.append(f.folder_id)
    expr = SORTS[sort]
    op = "<" if descending else ">"
    if after is not None:
        if sort == "date":
            if after.value is None:   # NULL : en dernier en décroissant, en premier en croissant
                where.append(f"(m.sent_at IS NULL AND m.id {op} ?)" if descending
                             else f"(m.sent_at IS NULL AND m.id {op} ?) OR m.sent_at IS NOT NULL")
                params.append(after.id)
            else:
                null_ok = " OR m.sent_at IS NULL" if descending else ""
                where.append(f"(m.sent_at {op} ? OR (m.sent_at = ? AND m.id {op} ?){null_ok})")
                params.extend([after.value, after.value, after.id])
        else:
            where.append(f"({expr} {op} ? OR ({expr} = ? AND m.id {op} ?))")
            params.extend([after.value, after.value, after.id])
    direction = "DESC" if descending else "ASC"
    order = f"{expr} {direction}, m.id {direction}"
    sort_value = f"{expr} AS sort_value"

    sql = f"""SELECT m.id, m.sent_at, m.sender, m.recipients, m.subject, m.archive_id,
                     a.path AS archive_path, fo.path AS folder_path, m.has_attachments,
                     {snippet} AS snip, {sort_value}
              FROM messages m {joins}
              JOIN archives a ON a.id = m.archive_id
              JOIN folders fo ON fo.id = m.folder_id
              {'WHERE ' + ' AND '.join(where) if where else ''}
              ORDER BY {order}
              LIMIT ?"""
    try:
        rows = conn.execute(sql, [*params, limit + 1]).fetchall()
    except sqlite3.OperationalError as exc:
        if pq.fts:      # syntaxe FTS5 refusée par le moteur (ex. champ imbriqué) : message clair, jamais d'erreur SQL
            raise QueryError("Requête non comprise : simplifiez-la (champs imbriqués non autorisés).") from exc
        raise
    more = len(rows) > limit
    rows = rows[:limit]
    hits = [Hit(r["id"], r["sent_at"], r["sender"], r["recipients"], r["subject"], r["archive_id"],
                r["archive_path"], r["folder_path"], bool(r["has_attachments"]), r["snip"] or "") for r in rows]
    nxt = Cursor(rows[-1]["sort_value"], rows[-1]["id"]) if more and rows else None
    return Page(hits, nxt)
