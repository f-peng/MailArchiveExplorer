"""Contrat commun des lecteurs d'archives."""
from __future__ import annotations

from typing import BinaryIO, Iterator, Protocol, runtime_checkable

from ..core.models import FolderInfo, RawMessage, ReadError


@runtime_checkable
class BaseReader(Protocol):
    reader_version: str

    def open(self) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> "BaseReader": ...
    def __exit__(self, *exc) -> None: ...
    def list_folders(self) -> Iterator[FolderInfo]: ...
    def iter_messages(self, folder: FolderInfo) -> Iterator[RawMessage | ReadError]:
        """Générateur. Une erreur sur un message est renvoyée comme ReadError, jamais levée."""
    def open_attachment(self, message_ref: str, index: int) -> BinaryIO:
        """Flux binaire du contenu de la pièce jointe, lu à la demande."""
