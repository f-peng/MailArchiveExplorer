"""Lecteur EML : fichier .eml unique ou répertoire (récursif)."""
from __future__ import annotations

import email
import io
from email import policy
from pathlib import Path
from typing import BinaryIO, Iterator

from ..core.models import FolderInfo, RawMessage, ReadError
from .email_parse import attachment_bytes, parse_bytes, to_raw_message, walk_attachments


class EmlReader:
    reader_version = "eml-1"

    def __init__(self, path: str | Path):
        self.root = Path(path)
        self._single = self.root.is_file()

    def open(self) -> None:
        if not self.root.exists():
            raise FileNotFoundError(self.root)

    def close(self) -> None: ...
    def __enter__(self): self.open(); return self
    def __exit__(self, *exc): self.close()

    def _dir_of(self, folder: FolderInfo) -> Path:
        base = self.root.parent if self._single else self.root
        return base.joinpath(*folder.path) if folder.path else base

    def list_folders(self) -> Iterator[FolderInfo]:
        if self._single:
            yield FolderInfo((), 1)
            return
        dirs = [self.root] + sorted(p for p in self.root.rglob("*") if p.is_dir() and not p.is_symlink())
        for d in dirs:
            rel = d.relative_to(self.root).parts
            n = sum(1 for p in d.iterdir() if p.suffix.lower() == ".eml" and not p.is_symlink() and p.is_file())
            if n:
                yield FolderInfo(tuple(rel) or (self.root.name,), n)

    def _folder_dir(self, folder: FolderInfo) -> Path:
        if self._single:
            return self.root.parent
        if folder.path == (self.root.name,) and not (self.root / folder.path[0]).is_dir():
            return self.root
        return self.root.joinpath(*folder.path)

    def iter_messages(self, folder: FolderInfo) -> Iterator[RawMessage | ReadError]:
        d = self._folder_dir(folder)
        files = [self.root] if self._single else sorted(p for p in d.iterdir() if p.suffix.lower() == ".eml")
        root_real = self.root.resolve()
        for f in files:
            if not self._single and (f.is_symlink() or not f.resolve().is_relative_to(root_real)):
                yield ReadError(f.name, folder.path, "symlink", "SymlinkIgnored", "lien symbolique ou fichier hors du dossier : ignoré")
                continue
            ref = str(f.relative_to(self.root.parent if self._single else self.root)) if not self._single else f.name
            try:
                msg = parse_bytes(f.read_bytes())
                yield to_raw_message(msg, ref, folder.path)
            except Exception as exc:  # noqa: BLE001
                yield ReadError(str(f.name), folder.path, "parse", type(exc).__name__, str(exc)[:200])

    def get_raw(self, message_ref: str) -> bytes | None:
        path = self.root if self._single else self.root / message_ref
        return path.read_bytes()

    def open_attachment(self, message_ref: str, index: int) -> BinaryIO:
        path = self.root if self._single else self.root / message_ref
        msg = parse_bytes(path.read_bytes())
        for idx, part in walk_attachments(msg):
            if idx == index:
                return io.BytesIO(attachment_bytes(part))
        raise IndexError(index)
