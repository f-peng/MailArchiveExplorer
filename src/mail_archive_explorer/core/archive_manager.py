"""Enregistrement des archives et ouverture du lecteur adapté."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ..readers.eml_reader import EmlReader
from ..readers.mbox_reader import MboxReader
from ..readers.olm_reader import OlmReader
from ..readers.pst.selector import choose_engine


def detect_kind(path: Path) -> str:
    if path.is_dir():
        return "eml"
    ext = path.suffix.lower()
    if ext in (".pst", ".ost"):
        return "pst"
    if ext == ".olm":
        return "olm"
    if ext in (".mbox", ".mbx"):
        return "mbox"
    if ext == ".eml":
        return "eml"
    raise ValueError(f"Type d'archive non reconnu : {path.name}")


def fingerprint(path: Path) -> str:
    """Taille + SHA-256 des 1 premiers Mo (détection rapide d'une archive déjà indexée)."""
    if path.is_dir():
        return "dir"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
    return f"{path.stat().st_size}:{h.hexdigest()}"


def open_reader(kind: str, path: str | Path, engine: str | None = None):
    path = Path(path)
    if kind == "pst":
        return choose_engine(path, engine)
    if kind == "mbox":
        return MboxReader(path)
    if kind == "olm":
        return OlmReader(path)
    return EmlReader(path)


def register_archive(conn: sqlite3.Connection, path: str | Path, engine: str | None = None) -> tuple[int, bool]:
    """Retourne (archive_id, déjà_connue). Le fichier n'est jamais modifié."""
    p = Path(path).resolve()
    kind = detect_kind(p)
    st = p.stat()
    row = conn.execute("SELECT id FROM archives WHERE path=? AND size=? AND mtime=?",
                       (str(p), st.st_size, st.st_mtime)).fetchone()
    if row:
        return row["id"], True
    cur = conn.execute(
        "INSERT INTO archives(path, kind, size, mtime, fingerprint, engine) VALUES (?,?,?,?,?,?)",
        (str(p), kind, st.st_size, st.st_mtime, fingerprint(p), engine))
    return cur.lastrowid, False


def remove_archive(conn: sqlite3.Connection, archive_id: int) -> None:
    """Retire l'archive de l'index (cascade). Le fichier source n'est pas touché."""
    conn.execute("DELETE FROM archives WHERE id=?", (archive_id,))


class ReaderCache:
    """Garde quelques lecteurs ouverts (UI uniquement) : relire un message ou une pièce jointe
    ne rouvre plus l'archive à chaque clic (OLM : annuaire ZIP, PST : fichier, readpst : conversion)."""

    def __init__(self, size: int = 2):
        self.size = size
        self._readers: dict[tuple, object] = {}

    def get(self, kind: str, path: str | Path, engine: str | None = None):
        key = (kind, str(path), engine)
        if key in self._readers:
            r = self._readers.pop(key)
            self._readers[key] = r                 # le plus récent en dernier
            return r
        r = open_reader(kind, path, engine if kind == "pst" else None)
        r.open()
        self._readers[key] = r
        while len(self._readers) > self.size:
            _, old = next(iter(self._readers.items()))
            self._readers.pop(next(iter(self._readers)))
            old.close()
        return r

    def evict(self, path: str | Path) -> None:
        for key in [k for k in self._readers if k[1] == str(path)]:
            self._readers.pop(key).close()

    def close_all(self) -> None:
        for r in self._readers.values():
            r.close()
        self._readers.clear()
