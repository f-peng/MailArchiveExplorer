"""Export : EML, MBOX, pièces jointes, résultats de recherche en CSV.

- MBOX/EML d'origine : les octets d'origine sont réexportés tels quels (en-têtes préservés).
- PST/OLM : l'archive ne fournit pas de message RFC 822 ; l'EML est **reconstruit** à partir des
  champs indexés (en-têtes principaux, corps texte/HTML, pièces jointes disponibles). Les en-têtes
  de transport d'origine (Received, DKIM...) ne sont pas réinjectés.
"""
from __future__ import annotations

import csv
import logging
import re
import sqlite3
import threading
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator

from ..core.archive_manager import ReaderCache
from ..core.search import Cursor, Filters, search
from .attachment_service import extract_stream, safe_destination, sanitize_filename

log = logging.getLogger(__name__)
Progress = Callable[[int, int], None]          # (faits, total)


@dataclass
class ExportReport:
    written: int = 0
    skipped: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    target: str = ""

    def error(self, msg: str) -> None:
        if len(self.errors) < 50:
            self.errors.append(msg)


def collect_ids(conn: sqlite3.Connection, query: str, filters: Filters, sort: str = "date",
                descending: bool = True) -> list[int]:
    """Tous les identifiants correspondant à une recherche (pagination keyset, mémoire bornée à la liste d'ids)."""
    ids: list[int] = []
    cursor: Cursor | None = None
    while True:
        page = search(conn, query, filters, after=cursor, limit=1000, sort=sort, descending=descending)
        ids.extend(h.id for h in page.hits)
        cursor = page.next_cursor
        if cursor is None:
            return ids


def _row(conn, mid):
    return conn.execute(
        "SELECT m.*, a.kind AS a_kind, a.path AS a_path, a.engine AS a_engine FROM messages m "
        "JOIN archives a ON a.id = m.archive_id WHERE m.id=?", (mid,)).fetchone()


def _set(msg: EmailMessage, name: str, value: str | None) -> None:
    if not value:
        return
    try:
        msg[name] = value
    except Exception:  # noqa: BLE001 - valeur d'en-tête non représentable : on neutralise
        msg[name] = re.sub(r"[^\x20-\x7e]", "?", value)


_MIME = re.compile(r"^[A-Za-z0-9][\w.+-]{0,60}/[A-Za-z0-9][\w.+-]{0,60}$")


def _ctype(mime: str | None) -> tuple[str, str]:
    if mime and _MIME.match(mime.strip()):
        a, b = mime.split("/", 1)
        return a, b
    return "application", "octet-stream"


def build_eml(conn: sqlite3.Connection, row, readers: ReaderCache) -> tuple[bytes, list[str]]:
    """Octets EML du message + liste d'avertissements (pièces jointes indisponibles...)."""
    warnings: list[str] = []
    reader = readers.get(row["a_kind"], row["a_path"], row["a_engine"])
    raw = reader.get_raw(row["source_ref"]) if hasattr(reader, "get_raw") else None
    if raw is not None:
        return raw, warnings

    msg = EmailMessage(policy=policy.SMTP)
    _set(msg, "From", row["sender"])
    to = row["to_addrs"] or (row["recipients"] if not (row["cc_addrs"] or row["bcc_addrs"]) else None)
    _set(msg, "To", to)
    _set(msg, "Cc", row["cc_addrs"])
    _set(msg, "Bcc", row["bcc_addrs"])
    _set(msg, "Subject", row["subject"])
    if row["sent_at"]:
        dt = datetime.strptime(row["sent_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        msg["Date"] = format_datetime(dt)
    _set(msg, "Message-ID", row["message_id"])
    msg["X-Exported-By"] = "Mail Archive Explorer (message reconstruit depuis une archive PST/OLM)"

    b = conn.execute("SELECT body_html FROM message_bodies WHERE message_id=?", (row["id"],)).fetchone()
    html = zlib.decompress(b["body_html"]).decode("utf-8", "replace") if b and b["body_html"] else None
    msg.set_content(row["body_text"] or "")
    if html:
        msg.add_alternative(html, subtype="html")
    for a in conn.execute("SELECT * FROM attachments WHERE message_id=? ORDER BY idx", (row["id"],)):
        try:
            data = reader.open_attachment(row["source_ref"], a["idx"]).read()
        except Exception as exc:  # noqa: BLE001 - contenu absent de l'archive (fréquent en OLM)
            warnings.append(f"pièce jointe « {a['filename']} » indisponible ({type(exc).__name__})")
            continue
        maintype, subtype = _ctype(a["mime"])
        target = msg.get_body(preferencelist=("html",)) or msg
        if a["content_id"] and a["is_inline"] and html:
            target.add_related(data, maintype=maintype, subtype=subtype, cid=f"<{re.sub(r'[^A-Za-z0-9._@+=$-]', '', a['content_id'] or '') or 'cid'}>")
        else:
            msg.add_attachment(data, maintype=maintype, subtype=subtype,
                               filename=sanitize_filename(a["filename"]))
    return msg.as_bytes(), warnings


def _name_for(row) -> str:
    date = (row["sent_at"] or "sans-date")[:10]
    subj = sanitize_filename(row["subject"] or "sans-objet", "sans-objet")[:60].rstrip(". ")
    return f"{date}_{subj}_{row['id']}.eml"


def _run(ids: list[int], report: ExportReport, progress: Progress | None, cancel: threading.Event | None,
         body: Callable[[int], None]) -> ExportReport:
    total = len(ids)
    for n, mid in enumerate(ids, 1):
        if cancel and cancel.is_set():
            report.cancelled = True
            break
        try:
            body(mid)
        except Exception as exc:  # noqa: BLE001 - une erreur n'arrête pas l'export
            report.skipped += 1
            report.error(f"message {mid} : {type(exc).__name__}: {str(exc)[:120]}")
            log.warning("Export message %s : %s", mid, exc)
        if progress and (n % 25 == 0 or n == total):
            progress(n, total)
    return report


def export_eml(conn, ids: list[int], dest_dir: Path, readers: ReaderCache,
               progress: Progress | None = None, cancel: threading.Event | None = None) -> ExportReport:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    rep = ExportReport(target=str(dest_dir))

    def one(mid):
        row = _row(conn, mid)
        data, warns = build_eml(conn, row, readers)
        path = safe_destination(dest_dir, _name_for(row))
        with open(path, "xb") as fh:            # O_EXCL : ne suit ni n'écrase un lien créé entre-temps
            fh.write(data)
        rep.written += 1
        for w in warns:
            rep.error(f"message {mid} : {w}")
    return _run(ids, rep, progress, cancel, one)


_FROM_ESC = re.compile(rb"^(>*From )", re.MULTILINE)


def _mbox_entry(row, data: bytes) -> bytes:
    """Entrée mboxrd : ligne « From », corps échappé, fin de ligne normalisée en LF, ligne vide finale."""
    when = datetime.strptime(row["sent_at"], "%Y-%m-%d %H:%M:%S") if row["sent_at"] else datetime(1970, 1, 1)
    sender = re.sub(r"[^\w.@+-]", "", (row["sender"] or "").split("<")[-1].strip(">")) or "MAILER-DAEMON"
    head = f"From {sender} {when.strftime('%a %b %d %H:%M:%S %Y')}\n".encode("ascii", "replace")
    body = _FROM_ESC.sub(rb">\1", data.replace(b"\r\n", b"\n"))
    return head + body.rstrip(b"\n") + b"\n\n"


def export_mbox(conn, ids: list[int], dest_file: Path, readers: ReaderCache,
                progress: Progress | None = None, cancel: threading.Event | None = None) -> ExportReport:
    dest_file = Path(dest_file)
    if dest_file.exists():
        raise FileExistsError(f"{dest_file} existe déjà : l'export ne remplace jamais un fichier.")
    rep = ExportReport(target=str(dest_file))
    with open(dest_file, "xb") as out:
        def one(mid):
            row = _row(conn, mid)
            data, warns = build_eml(conn, row, readers)
            out.write(_mbox_entry(row, data))
            rep.written += 1
            for w in warns:
                rep.error(f"message {mid} : {w}")
        _run(ids, rep, progress, cancel, one)
    return rep


def export_attachments(conn, ids: list[int], dest_dir: Path, readers: ReaderCache,
                       progress: Progress | None = None, cancel: threading.Event | None = None) -> ExportReport:
    """Extrait les pièces jointes ; un sous-dossier par message évite les collisions de noms."""
    dest_dir = Path(dest_dir)
    rep = ExportReport(target=str(dest_dir))

    def one(mid):
        row = _row(conn, mid)
        atts = conn.execute("SELECT * FROM attachments WHERE message_id=? ORDER BY idx", (mid,)).fetchall()
        if not atts:
            return
        reader = readers.get(row["a_kind"], row["a_path"], row["a_engine"])
        sub = dest_dir / f"{(row['sent_at'] or 'sans-date')[:10]}_{mid}"
        for a in atts:
            try:
                path, digest = extract_stream(reader.open_attachment(row["source_ref"], a["idx"]), sub, a["filename"])
                rep.written += 1
            except Exception as exc:  # noqa: BLE001
                rep.skipped += 1
                rep.error(f"message {mid} « {a['filename']} » : {type(exc).__name__}: {str(exc)[:100]}")
    return _run(ids, rep, progress, cancel, one)


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Neutralise l'injection de formules (Excel/LibreOffice) en préfixant d'une apostrophe."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA) else s


CSV_HEADER = ["Date (UTC)", "Expéditeur", "Destinataires", "Objet", "Archive", "Dossier", "Pièces jointes", "Extrait"]


def export_csv(conn, query: str, filters: Filters, dest_file: Path, sort: str = "date", descending: bool = True,
               progress: Progress | None = None, cancel: threading.Event | None = None) -> ExportReport:
    """Résultats d'une recherche (tous, pas seulement la page affichée), UTF-8 avec BOM."""
    dest_file = Path(dest_file)
    if dest_file.exists():
        raise FileExistsError(f"{dest_file} existe déjà : l'export ne remplace jamais un fichier.")
    rep = ExportReport(target=str(dest_file))
    cursor = None
    with open(dest_file, "x", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(CSV_HEADER)
        while True:
            if cancel and cancel.is_set():
                rep.cancelled = True
                break
            page = search(conn, query, filters, after=cursor, limit=1000, sort=sort, descending=descending)
            for h in page.hits:
                w.writerow([csv_safe(x) for x in (
                    h.sent_at or "", h.sender or "", h.recipients or "", h.subject or "",
                    Path(h.archive_path).name, h.folder_path, "oui" if h.has_attachments else "non",
                    " ".join(h.snippet.split()) if query.strip() else "")])
                rep.written += 1
            if progress:
                progress(rep.written, rep.written)
            cursor = page.next_cursor
            if cursor is None:
                break
    return rep
