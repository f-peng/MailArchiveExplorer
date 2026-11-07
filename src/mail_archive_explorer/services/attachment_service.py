"""Extraction de pièces jointes : assainissement des noms, anti-traversée."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Callable, BinaryIO

_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME = 120


def sanitize_filename(name: str | None, fallback: str = "piece_jointe") -> str:
    """Nom sûr et portable : pas de séparateur, pas de '..', pas de nom réservé Windows, longueur bornée."""
    n = unicodedata.normalize("NFC", name or "")
    n = n.replace("/", "_").replace("\\", "_")
    n = _FORBIDDEN.sub("_", n).strip(" .")
    if not n or set(n) <= {"."}:
        n = fallback
    stem, dot, ext = n.rpartition(".")
    if not dot:
        stem, ext = n, ""
    if stem.upper() in _WIN_RESERVED:
        stem = f"_{stem}"
    ext = ext[:16]
    stem = stem[: MAX_NAME - len(ext) - 1]
    return f"{stem}.{ext}" if ext else stem


def safe_destination(dest_dir: Path, name: str | None) -> Path:
    """Chemin final garanti sous dest_dir ; ne remplace jamais un fichier ni un lien symbolique."""
    dest_dir = Path(dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = sanitize_filename(name)
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    candidate, i = dest_dir / base, 1
    while candidate.exists() or candidate.is_symlink():
        candidate = dest_dir / (f"{stem} ({i})" + (f".{ext}" if ext else ""))
        i += 1
    if candidate.resolve().parent != dest_dir:
        raise ValueError("Chemin de destination hors du répertoire autorisé")
    return candidate


def extract_stream(stream: BinaryIO, dest_dir: Path, name: str | None) -> tuple[Path, str]:
    """Écrit le flux en blocs (mémoire bornée) et renvoie (chemin, sha256)."""
    import hashlib
    target = safe_destination(dest_dir, name)
    h = hashlib.sha256()
    with open(target, "xb") as out:
        while block := stream.read(1 << 20):
            h.update(block)
            out.write(block)
    return target, h.hexdigest()
