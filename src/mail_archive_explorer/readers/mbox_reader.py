"""Lecteur MBOX par décalages d'octets : ouverture et lecture d'un message en O(taille du message).

Le fichier est parcouru une seule fois en flux (jamais chargé en mémoire) pour repérer les
séparateurs « From » ; `ref` = « décalage:longueur », ce qui permet de relire un message
(images incorporées, pièces jointes) sans re-balayer un MBOX de plusieurs Go."""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import BinaryIO, Iterator

from ..core.i18n import tr
from ..core.models import FolderInfo, RawMessage, ReadError
from .email_parse import attachment_bytes, parse_bytes, to_raw_message, walk_attachments


# « From expéditeur Mon Dec  3 10:00:00 2024 » (les dates varient : secondes, fuseau, année)
_FROM_LINE = re.compile(rb"^From \S+\s+(?:\w{3},?\s+)?\w{3}\s+\d{1,2}\s+\d\d:\d\d|^From \S+\s+\d{1,2}\s+\w{3}\s+\d{4}")


MAX_MESSAGE_BYTES = 64 * 1024 * 1024    # plafond d'un message lu en mémoire
_CHUNK = 65536                           # une « ligne » plus longue est lue par morceaux (MBOX sans saut de ligne)


def scan_offsets(path: Path) -> Iterator[tuple[int, int]]:
    """(début, longueur) de chaque message. Séparateur : ligne « From » en début de fichier
    ou précédée d'une ligne vide (mboxo/mboxrd)."""
    start = None
    prev_blank = True
    at_line_start = True
    pos = 0
    with open(path, "rb") as f:
        while True:
            line = f.readline(_CHUNK)         # mémoire bornée même sans saut de ligne
            if not line:
                break
            if at_line_start and prev_blank and line.startswith(b"From ") and _FROM_LINE.match(line):
                if start is not None:
                    yield start, pos - start
                start = pos + len(line)      # le contenu commence après la ligne « From »
            if at_line_start:
                prev_blank = line in (b"\n", b"\r\n")
            at_line_start = line.endswith(b"\n")
            pos += len(line)
    if start is not None and pos > start:
        yield start, pos - start


class MboxReader:
    reader_version = "mbox-2"
    name = "mbox"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fh: BinaryIO | None = None

    def open(self) -> None:
        self._fh = open(self.path, "rb")      # lecture seule

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self): self.open(); return self
    def __exit__(self, *exc): self.close()

    def list_folders(self) -> Iterator[FolderInfo]:
        yield FolderInfo((self.path.stem,), None)   # total inconnu sans balayage : pas de pourcentage fictif

    def _read(self, ref: str) -> bytes:
        if ":" not in ref:
            raise ValueError(tr("Référence MBOX ancienne (format < 2) : décharger puis recharger cette archive."))
        off, _, length = ref.partition(":")
        if int(length) > MAX_MESSAGE_BYTES:
            raise ValueError(tr("message de {a} Mo : au-delà du plafond ({b} Mo)").format(a=int(length) // 1_000_000, b=MAX_MESSAGE_BYTES // 1_000_000))
        self._fh.seek(int(off))
        return self._fh.read(int(length))

    def iter_messages(self, folder: FolderInfo) -> Iterator[RawMessage | ReadError]:
        for off, length in scan_offsets(self.path):
            ref = f"{off}:{length}"
            try:
                yield to_raw_message(parse_bytes(self._read(ref)), ref, folder.path)
            except Exception as exc:  # noqa: BLE001
                yield ReadError(ref, folder.path, "parse", type(exc).__name__, str(exc)[:200])

    def get_raw(self, message_ref: str) -> bytes | None:
        """Octets d'origine du message (export EML/MBOX fidèle)."""
        return self._read(message_ref)

    def open_attachment(self, message_ref: str, index: int) -> BinaryIO:
        for idx, part in walk_attachments(parse_bytes(self._read(message_ref))):
            if idx == index:
                return io.BytesIO(attachment_bytes(part))
        raise IndexError(index)
