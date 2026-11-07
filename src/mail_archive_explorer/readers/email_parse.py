"""Conversion email.message.Message -> RawMessage (MBOX, EML, sortie de readpst).

Les messages sont analysés avec la politique `compat32` : ~12x plus rapide que
`policy.default` (mesuré : ~12 600 contre ~1 030 messages/s). Le décodage des en-têtes
(RFC 2047) et des corps est fait ici, explicitement."""
from __future__ import annotations

import email
import email.utils
import mimetypes
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from typing import Iterable

from ..core.charset import decode_body
from ..core.models import RawAddress, RawAttachment, RawMessage

PARSE_POLICY = email.policy.compat32 if hasattr(email, "policy") else None


def parse_bytes(data: bytes) -> Message:
    from email import policy
    return email.message_from_bytes(data, policy=policy.compat32)


def clean_str(value: str) -> str:
    """Remplace les octets 8 bits bruts (surrogateescape, produits par compat32 pour un en-tête non
    encodé comme « Subject: Café ») par leur décodage UTF-8, à défaut cp1252 : jamais de substitut isolé."""
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        raw = value.encode("utf-8", "surrogateescape")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", errors="replace")


def raw_all(msg: Message, name: str) -> list[str]:
    """Valeurs brutes d'un en-tête. `msg.get()` renvoie, pour un en-tête 8 bits non encodé, un objet
    Header dont str() contient des U+FFFD (octets perdus) : on lit donc les valeurs brutes."""
    low = name.lower()
    return [v if isinstance(v, str) else str(v) for k, v in msg.raw_items() if k.lower() == low]


def raw_first(msg: Message, name: str) -> str | None:
    vals = raw_all(msg, name)
    return vals[0] if vals else None


def decode_header_value(value) -> str | None:
    """Décode un en-tête (mots encodés RFC 2047) ; ne lève jamais d'exception."""
    if value is None:
        return None
    raw = clean_str(str(value))
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:  # noqa: BLE001 - jeu de caractères inconnu, en-tête corrompu
        return raw.strip()


def parse_addresses(values: Iterable) -> tuple[RawAddress, ...]:
    out = []
    for name, addr in email.utils.getaddresses([clean_str(str(v)) for v in values if v is not None]):
        name = decode_header_value(name) if name else None
        if name or addr:
            out.append(RawAddress(name or None, addr or None))
    return tuple(out)


def parse_date(value) -> tuple[datetime | None, bool]:
    if not value:
        return None, False
    try:
        dt = email.utils.parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError):
        return None, False
    if dt is None:
        return None, False
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt, True


def _part_text(part: Message) -> str | None:
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001
        return None
    if payload is None:
        return None
    return decode_body(payload, part.get_content_charset())


def _is_attachment(part: Message) -> bool:
    disp = part.get_content_disposition()
    ctype = part.get_content_type()
    if disp == "attachment" or part.get_filename():
        return True
    if part.get("Content-ID") and not ctype.startswith("text/"):
        return True
    return False


def walk_attachments(msg: Message) -> list[tuple[int, Message]]:
    """Parties traitées comme pièces jointes, dans un ordre stable (même ordre à l'import et à l'extraction)."""
    out: list[tuple[int, Message]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if _is_attachment(part):
            out.append((len(out), part))
    return out


def attachment_bytes(part: Message) -> bytes:
    return part.get_payload(decode=True) or b""


def to_raw_message(msg: Message, ref: str, folder_path: tuple[str, ...]) -> RawMessage:
    sent, valid = parse_date(raw_first(msg, "Date"))
    text = html = None
    for part in msg.walk():
        if part.is_multipart() or _is_attachment(part):
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and text is None:
            text = _part_text(part)
        elif ctype == "text/html" and html is None:
            html = _part_text(part)
    attachments = []
    for idx, part in walk_attachments(msg):
        name = decode_header_value(part.get_filename())
        payload = part.get_payload(decode=True)
        cid = raw_first(part, "Content-ID")
        attachments.append(RawAttachment(
            index=idx, filename=name,
            mime=part.get_content_type() or mimetypes.guess_type(name or "")[0],
            size=len(payload) if payload is not None else None,
            content_id=clean_str(str(cid)).strip("<> ") if cid else None,
            is_inline=part.get_content_disposition() == "inline",
        ))
    from_addrs = parse_addresses(raw_all(msg, "From"))
    headers = clean_str("".join(f"{k}: {v}\n" for k, v in msg.raw_items()))
    mid = raw_first(msg, "Message-ID")
    return RawMessage(
        ref=ref, folder_path=folder_path,
        message_id=clean_str(str(mid)).strip() if mid else None,
        subject=decode_header_value(raw_first(msg, "Subject")),
        sender=from_addrs[0] if from_addrs else None,
        to=parse_addresses(raw_all(msg, "To")),
        cc=parse_addresses(raw_all(msg, "Cc")),
        bcc=parse_addresses(raw_all(msg, "Bcc")),
        sent_at=sent, date_valid=valid, body_text=text, body_html=html,
        headers=headers, attachments=tuple(attachments), message_class="IPM.Note",
    )
