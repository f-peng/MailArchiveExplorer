"""Moteur PST de repli : readpst (libpst) en sous-processus -> EML temporaires."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO, Iterator

from ...core.models import FolderInfo, RawMessage, ReadError
from ..eml_reader import EmlReader
from .engine import ProbeResult


def find_readpst() -> str | None:
    return shutil.which("readpst")


class ReadpstEngine:
    name = "readpst"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._eml: EmlReader | None = None
        self.reader_version = "readpst"
        self.stderr = ""

    @classmethod
    def is_available(cls) -> bool:
        return find_readpst() is not None

    @staticmethod
    def probe(path: Path) -> ProbeResult:
        if not path.exists():
            return ProbeResult(False, detail="fichier introuvable")
        return ProbeResult(path.stat().st_size > 0, "PST", path.stat().st_size,
                           detail="" if path.stat().st_size else "fichier vide")

    def open(self) -> None:
        exe = find_readpst()
        if not exe:
            raise RuntimeError("readpst introuvable dans le PATH")
        self.reader_version = subprocess.run([exe, "-V"], capture_output=True, text=True).stdout.splitlines()[0]
        self._tmp = tempfile.TemporaryDirectory(prefix="mae_readpst_")
        out = Path(self._tmp.name)
        proc = subprocess.run([exe, "-q", "-r", "-e", "-8", "-o", str(out), str(self.path)],
                              capture_output=True, text=True)
        self.stderr = proc.stderr
        if proc.returncode != 0:
            raise RuntimeError(f"readpst a échoué (code {proc.returncode}) : {proc.stderr[:200]}")
        self._eml = EmlReader(out)
        self._eml.open()

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def __enter__(self): self.open(); return self
    def __exit__(self, *exc): self.close()

    def list_folders(self) -> Iterator[FolderInfo]:
        yield from self._eml.list_folders()

    def iter_messages(self, folder: FolderInfo) -> Iterator[RawMessage | ReadError]:
        yield from self._eml.iter_messages(folder)

    def get_raw(self, message_ref: str) -> bytes | None:
        return self._eml.get_raw(message_ref)

    def open_attachment(self, message_ref: str, index: int) -> BinaryIO:
        return self._eml.open_attachment(message_ref, index)
