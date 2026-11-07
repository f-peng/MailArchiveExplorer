"""Empreintes : content_hash des messages et SHA-256 de flux."""
from __future__ import annotations

import hashlib
import re
from typing import BinaryIO

from ..core.models import RawMessage

_PREFIX = re.compile(r"^\s*((re|fwd?|tr|réf|ref)\s*:\s*)+", re.IGNORECASE)
_WS = re.compile(r"\s+")


def clean_subject(subject: str | None) -> str:
    return _PREFIX.sub("", subject or "").strip().lower()


def normalize_body(text: str | None) -> str:
    return _WS.sub(" ", (text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def content_hash(msg: RawMessage) -> str:
    """SHA-256 de : Message-ID, expéditeur (minuscules), destinataires triés,
    objet sans préfixes Re:/Fwd:, date UTC à la minute, corps normalisé.
    Champs séparés par \\x1f ; une valeur absente donne un champ vide."""
    sender = (msg.sender.email or msg.sender.name or "").lower() if msg.sender else ""
    rcpts = sorted((a.email or a.name or "").lower() for a in (*msg.to, *msg.cc, *msg.bcc))
    date = msg.sent_at.strftime("%Y-%m-%dT%H:%M") if msg.sent_at else ""
    parts = [
        (msg.message_id or "").strip().lower(),
        sender,
        ",".join(rcpts),
        clean_subject(msg.subject),
        date,
        normalize_body(msg.body_text),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()


def sha256_stream(stream: BinaryIO, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    while block := stream.read(chunk):
        h.update(block)
    return h.hexdigest()
