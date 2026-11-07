"""Accès SQLite : pragmas, migrations par user_version, sauvegarde."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrations import MIGRATIONS


def connect(path: str | Path, *, readonly: bool = False, bulk: bool = False) -> sqlite3.Connection:
    uri = f"{Path(path).resolve().as_uri()}?mode={'ro' if readonly else 'rwc'}"   # caractères spéciaux (# ? %) échappés
    conn = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA synchronous={'NORMAL' if bulk else 'FULL'}")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def apply_migrations(conn: sqlite3.Connection) -> int:
    current = schema_version(conn)
    target = max(MIGRATIONS)
    if current > target:
        raise RuntimeError(f"Base de schéma {current} plus récente que l'application ({target}).")
    for n in range(current + 1, target + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split(MIGRATIONS[n]):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version={n}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return target


def _split(script: str) -> list[str]:
    """Découpe un script en instructions complètes (gère les corps de triggers)."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def open_database(path: str | Path, *, bulk: bool = False) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path, bulk=bulk)
    apply_migrations(conn)
    return conn


def backup(conn: sqlite3.Connection, dest: str | Path) -> None:
    """Sauvegarde cohérente via l'API de sauvegarde SQLite.
    Restauration : fermer l'application et remplacer le fichier .db par la copie."""
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    finally:
        target.close()
