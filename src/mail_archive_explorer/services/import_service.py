"""Import d'une archive en base : lots, reprise, idempotence, erreurs comptées."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import zlib
from dataclasses import dataclass, field
from typing import Callable

from ..core.archive_manager import open_reader, register_archive
from ..core.models import FolderInfo, RawMessage, ReadError
from ..core.textutil import scrub
from .hashing import content_hash

log = logging.getLogger(__name__)
BATCH_SIZE = 500
MAX_INDEXED_BODY = 1_000_000  # caractères indexés par message (plafond)


@dataclass
class ImportReport:
    archive_id: int = 0
    engine: str = ""
    imported: int = 0
    skipped_existing: int = 0
    skipped_non_mail: int = 0
    skipped_empty: int = 0        # messages sans aucun contenu (métadonnées seules, constaté en OLM)
    errors: int = 0
    cancelled: bool = False
    error_samples: list[str] = field(default_factory=list)


class ProgressSink:
    """Interface de progression. `total` vaut None quand il est inconnu."""
    def on_folder(self, path: tuple[str, ...], total: int | None) -> None: ...
    def on_progress(self, folder: tuple[str, ...], done: int, errors: int) -> None: ...


def _fmt_date(msg: RawMessage) -> str | None:
    return msg.sent_at.strftime("%Y-%m-%d %H:%M:%S") if msg.sent_at else None


def _join(addrs) -> str | None:
    return ", ".join(a.display() for a in addrs) or None


def _excerpt(text: str | None) -> str:
    return " ".join((text or "")[:600].split())[:200]


def _insert_message(conn: sqlite3.Connection, archive_id: int, folder_id: int, msg: RawMessage) -> bool:
    S = scrub
    body = S((msg.body_text or "")[:MAX_INDEXED_BODY])
    names = S(" ".join(a.filename for a in msg.attachments if a.filename))
    rcpts = S(", ".join(a.display() for a in (*msg.to, *msg.cc, *msg.bcc)))
    cur = conn.execute(
        """INSERT OR IGNORE INTO messages(archive_id, folder_id, source_ref, message_id, content_hash,
           subject, sender, recipients, sent_at, date_valid, body_text, excerpt,
           has_attachments, attachment_names, message_class, to_addrs, cc_addrs, bcc_addrs)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (archive_id, folder_id, msg.ref, S(msg.message_id), content_hash(msg), S(msg.subject),
         S(msg.sender.display()) if msg.sender else None, rcpts, _fmt_date(msg), int(msg.date_valid),
         body, _excerpt(body), int(bool(msg.attachments)), names or None, msg.message_class,
         S(_join(msg.to)), S(_join(msg.cc)), S(_join(msg.bcc))))
    if cur.rowcount == 0:
        return False
    mid = cur.lastrowid
    conn.execute("INSERT INTO message_bodies(message_id, body_html, headers) VALUES (?,?,?)",
                 (mid, zlib.compress(S(msg.body_html).encode("utf-8")) if msg.body_html else None,
                  zlib.compress(S(msg.headers).encode("utf-8")) if msg.headers else None))
    for a in msg.attachments:
        conn.execute(
            """INSERT INTO attachments(message_id, idx, filename, mime, size, content_id, is_inline, attach_method)
               VALUES (?,?,?,?,?,?,?,?)""",
            (mid, a.index, S(a.filename), S(a.mime), a.size if (a.size is None or 0 <= a.size < 2**53) else None,
             S(a.content_id), int(a.is_inline), a.attach_method))
    conn.execute("INSERT OR IGNORE INTO message_sources(message_id, archive_id, folder_path) VALUES (?,?,?)",
                 (mid, archive_id, "/".join(msg.folder_path)))
    return True


def import_archive(conn: sqlite3.Connection, path, *, engine: str | None = None,
                   progress: ProgressSink | None = None,
                   cancel: threading.Event | None = None,
                   batch_size: int = BATCH_SIZE) -> ImportReport:
    """`conn` doit être en autocommit (isolation_level=None) : les transactions sont explicites."""
    progress = progress or ProgressSink()
    report = ImportReport()
    archive_id, _known = register_archive(conn, path, engine)
    report.archive_id = archive_id
    kind = conn.execute("SELECT kind FROM archives WHERE id=?", (archive_id,)).fetchone()["kind"]

    with open_reader(kind, path, engine) as reader:
        report.engine = getattr(reader, "name", kind)
        conn.execute("UPDATE archives SET engine=? WHERE id=?", (report.engine, archive_id))
        for folder in reader.list_folders():
            if cancel and cancel.is_set():
                report.cancelled = True
                break
            _import_folder(conn, reader, archive_id, folder, report, progress, cancel, batch_size)
    return report


def _import_folder(conn, reader, archive_id, folder: FolderInfo, report, progress, cancel, batch_size):
    fpath = "/".join(folder.path)
    cp = conn.execute("SELECT done FROM import_checkpoints WHERE archive_id=? AND folder_path=?",
                      (archive_id, fpath)).fetchone()
    if cp and cp["done"]:
        return
    conn.execute("INSERT OR IGNORE INTO folders(archive_id, name, path) VALUES (?,?,?)",
                 (archive_id, folder.path[-1] if folder.path else "", fpath))
    folder_id = conn.execute("SELECT id FROM folders WHERE archive_id=? AND path=?", (archive_id, fpath)).fetchone()["id"]
    conn.execute("INSERT OR IGNORE INTO import_checkpoints(archive_id, folder_path) VALUES (?,?)", (archive_id, fpath))
    progress.on_folder(folder.path, folder.message_count)

    done = errors = 0
    in_batch = 0
    last_ref = None
    conn.execute("BEGIN")
    try:
        for item in reader.iter_messages(folder):
            if cancel and cancel.is_set():
                report.cancelled = True
                break
            if isinstance(item, ReadError):
                errors += 1
                report.errors += 1
                if len(report.error_samples) < 20:
                    report.error_samples.append(f"{fpath}:{item.ref} {item.exception_type}: {item.detail}")
                log.warning("Erreur de lecture %s:%s %s %s", fpath, item.ref, item.exception_type, item.detail)
                continue
            last_ref = item.ref
            if item.message_class == "IPM.Empty":
                report.skipped_empty += 1
                continue
            if item.message_class and not item.message_class.startswith("IPM.Note"):
                report.skipped_non_mail += 1
                continue
            conn.execute("SAVEPOINT msg")          # un message défectueux n'annule ni le lot ni l'import
            try:
                inserted = _insert_message(conn, archive_id, folder_id, item)
                conn.execute("RELEASE msg")
                if inserted:
                    report.imported += 1
                else:
                    report.skipped_existing += 1
            except (sqlite3.Error, OverflowError, UnicodeError, ValueError, LookupError, TypeError) as exc:
                conn.execute("ROLLBACK TO msg")
                conn.execute("RELEASE msg")
                errors += 1
                report.errors += 1
                if len(report.error_samples) < 20:
                    report.error_samples.append(f"{fpath}:{item.ref} {type(exc).__name__}: {str(exc)[:120]}")
                log.warning("Erreur d'écriture %s:%s %s", fpath, item.ref, exc)
            done += 1
            in_batch += 1
            if in_batch >= batch_size:
                _checkpoint(conn, archive_id, fpath, last_ref, done, errors, False)
                conn.execute("COMMIT")
                conn.execute("BEGIN")
                in_batch = 0
                progress.on_progress(folder.path, done, errors)
        finished = not report.cancelled
        _checkpoint(conn, archive_id, fpath, last_ref, done, errors, finished)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    progress.on_progress(folder.path, done, errors)


def _checkpoint(conn, archive_id, fpath, last_ref, done, errors, finished):
    """Compteurs cumulés de la passe en cours (écrits dans la même transaction que le lot)."""
    conn.execute(
        "UPDATE import_checkpoints SET last_ref=?, processed=?, errors=?, done=? WHERE archive_id=? AND folder_path=?",
        (last_ref, done, errors, int(finished), archive_id, fpath))
