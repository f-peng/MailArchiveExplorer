"""Modèles normalisés échangés entre lecteurs, services et base."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class RawAddress:
    name: str | None = None
    email: str | None = None

    def display(self) -> str:
        if self.name and self.email and self.name != self.email:
            return f"{self.name} <{self.email}>"
        return self.name or self.email or ""


@dataclass(frozen=True)
class RawAttachment:
    index: int
    filename: str | None
    mime: str | None
    size: int | None
    content_id: str | None = None
    is_inline: bool = False
    attach_method: int | None = None


@dataclass(frozen=True)
class RawMessage:
    """Message normalisé. `ref` identifie le message dans la source (re-lecture à la demande)."""
    ref: str
    folder_path: tuple[str, ...]
    message_id: str | None = None
    subject: str | None = None
    sender: RawAddress | None = None
    to: tuple[RawAddress, ...] = ()
    cc: tuple[RawAddress, ...] = ()
    bcc: tuple[RawAddress, ...] = ()
    sent_at: datetime | None = None  # UTC naïf
    date_valid: bool = True
    body_text: str | None = None
    body_html: str | None = None
    has_rtf: bool = False
    headers: str | None = None
    attachments: tuple[RawAttachment, ...] = ()
    message_class: str | None = None
    props: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FolderInfo:
    path: tuple[str, ...]
    message_count: int | None = None


@dataclass(frozen=True)
class ReadError:
    ref: str
    folder_path: tuple[str, ...]
    stage: str
    exception_type: str
    detail: str
