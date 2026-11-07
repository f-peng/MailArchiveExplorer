"""Moteur PST principal : lecture directe via pypff (libpff)."""
from __future__ import annotations

import io
import mimetypes
from datetime import datetime
from email import message_from_string, policy
from pathlib import Path
from typing import BinaryIO, Iterator

from ...core.charset import decode_body
from ...core.models import (FolderInfo, RawAddress, RawAttachment, RawMessage, ReadError)
from ..email_parse import parse_addresses
from .engine import ProbeResult
from .rtf import rtf_to_text

try:
    import pypff
except ImportError:  # pragma: no cover
    pypff = None

PR_MESSAGE_CLASS = 0x001A
PR_SENDER_NAME = 0x0C1A
PR_SENDER_EMAIL = 0x0C1F
PR_SENDER_SMTP = 0x5D01
PR_INTERNET_MESSAGE_ID = 0x1035
PR_MESSAGE_CODEPAGE = 0x3FFD
PR_INTERNET_CPID = 0x3FDE
PR_RECIPIENT_TYPE = 0x0C15
PR_DISPLAY_NAME = 0x3001
PR_EMAIL_ADDRESS = 0x3003
PR_SMTP_ADDRESS = 0x39FE
PR_ATTACH_METHOD = 0x3705
PR_ATTACH_LONG_FILENAME = 0x3707
PR_ATTACH_FILENAME = 0x3704
PR_ATTACH_MIME_TAG = 0x370E
PR_ATTACH_CONTENT_ID = 0x3712

_STRING_TYPES = (30, 31)


def _props(record_sets) -> dict[int, object]:
    out = {}
    for rs in record_sets:
        for e in rs.entries:
            out.setdefault(e.entry_type, e)
    return out


def _s(ent) -> str | None:
    if ent is None:
        return None
    try:
        if ent.value_type in _STRING_TYPES:
            v = ent.get_data_as_string()
            return v if v else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _i(ent) -> int | None:
    if ent is None:
        return None
    try:
        return ent.get_data_as_integer()
    except Exception:  # noqa: BLE001
        return None


def _real_email(value: str | None) -> str | None:
    """Une adresse Exchange interne (X.500, /O=...) n'est pas une adresse SMTP."""
    return value if value and "@" in value and not value.startswith("/") else None


class _AttachmentStream(io.RawIOBase):
    """Flux de lecture à la demande d'une pièce jointe pypff (pas de chargement complet)."""

    def __init__(self, att):
        self._att = att

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self._att.read_buffer(len(b))
        n = len(data)
        b[:n] = data
        return n


class PypffEngine:
    name = "pypff"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = None
        self.reader_version = f"pypff-{pypff.get_version()}" if pypff else "pypff-absent"
        self._codepage: str | None = None

    # -- disponibilité / sonde -------------------------------------------------
    @classmethod
    def is_available(cls) -> bool:
        return pypff is not None

    @staticmethod
    def probe(path: Path) -> ProbeResult:
        if pypff is None:
            return ProbeResult(False, detail="pypff indisponible")
        try:
            size = Path(path).stat().st_size
            if not pypff.check_file_signature(str(path)):
                return ProbeResult(False, size=size, detail="signature PST/OST invalide")
            f = pypff.file()
            f.open(str(path))
            try:
                kind = {112: "PST", 111: "OST"}.get(f.get_content_type(), "PST")
                return ProbeResult(True, kind, size, f.get_encryption_type() not in (0, 1))
            finally:
                f.close()
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(False, detail=f"{type(exc).__name__}: {str(exc)[:160]}")

    # -- cycle de vie ----------------------------------------------------------
    def open(self) -> None:
        f = pypff.file()
        f.open(str(self.path))  # lecture seule
        self._file = f
        cp = f.get_ascii_codepage()
        self._codepage = cp.decode("ascii", "ignore") if isinstance(cp, bytes) else cp

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self): self.open(); return self
    def __exit__(self, *exc): self.close()

    # -- dossiers --------------------------------------------------------------
    def _folder_at(self, idx_path: tuple[int, ...]):
        folder = self._file.get_root_folder()
        for i in idx_path:
            folder = folder.get_sub_folder(i)
        return folder

    def _walk(self, folder, idx_path, names) -> Iterator[tuple[tuple[int, ...], tuple[str, ...], object]]:
        for i in range(folder.get_number_of_sub_folders()):
            sub = folder.get_sub_folder(i)
            n = sub.get_name() or f"(dossier {i})"
            yield (*idx_path, i), (*names, n), sub
            yield from self._walk(sub, (*idx_path, i), (*names, n))

    def list_folders(self) -> Iterator[FolderInfo]:
        root = self._file.get_root_folder()
        self._index: dict[tuple[str, ...], tuple[int, ...]] = {}
        for idx_path, names, sub in self._walk(root, (), ()):
            self._index[names] = idx_path
            count = sub.get_number_of_sub_messages()
            if count:
                yield FolderInfo(names, count)

    # -- messages --------------------------------------------------------------
    def iter_messages(self, folder: FolderInfo) -> Iterator[RawMessage | ReadError]:
        if not hasattr(self, "_index"):
            list(self.list_folders())
        idx_path = self._index[folder.path]
        pf = self._folder_at(idx_path)
        prefix = ".".join(map(str, idx_path))
        for i in range(pf.get_number_of_sub_messages()):
            ref = f"{prefix}:{i}"
            try:
                msg = pf.get_sub_message(i)
                if not hasattr(msg, "get_subject"):
                    # contacts, éléments non-message : classe MAPI lue sur l'item générique
                    yield self._non_message(msg, ref, folder.path)
                    continue
                yield self._convert(msg, ref, folder.path)
            except Exception as exc:  # noqa: BLE001
                yield ReadError(ref, folder.path, "message", type(exc).__name__, str(exc)[:200])

    def _non_message(self, item, ref, path) -> RawMessage:
        cls = None
        try:
            cls = _s(_props(item.record_sets).get(PR_MESSAGE_CLASS))
        except Exception:  # noqa: BLE001
            pass
        return RawMessage(ref=ref, folder_path=path, message_class=cls or "IPM.Unknown")

    def _convert(self, msg, ref, path) -> RawMessage:
        p = _props(msg.record_sets)
        cls = _s(p.get(PR_MESSAGE_CLASS))
        if cls and not cls.startswith("IPM.Note"):
            # rendez-vous, contacts, tâches... : hors périmètre MVP, signalés par leur classe
            return RawMessage(ref=ref, folder_path=path, message_class=cls, subject=_s(p.get(0x0037)))
        hints = (_i(p.get(PR_INTERNET_CPID)), _i(p.get(PR_MESSAGE_CODEPAGE)), self._codepage)
        headers = None
        try:
            raw = msg.get_transport_headers()
            headers = decode_body(raw, *hints) if raw else None
        except Exception:  # noqa: BLE001
            pass
        parsed = None
        if headers:
            try:
                parsed = message_from_string(headers, policy=policy.default)
            except Exception:  # noqa: BLE001
                parsed = None

        subject = None
        try:
            subject = msg.get_subject()
        except Exception:  # noqa: BLE001
            pass
        subject = subject or _s(p.get(0x0037))

        # expéditeur
        s_name = _s(p.get(PR_SENDER_NAME))
        s_mail = _real_email(_s(p.get(PR_SENDER_SMTP))) or _real_email(_s(p.get(PR_SENDER_EMAIL)))
        if not s_mail and parsed is not None:
            hs = parse_addresses(parsed.get_all("From", []))
            if hs:
                s_mail = hs[0].email
                s_name = s_name or hs[0].name
        sender = RawAddress(s_name, s_mail) if (s_name or s_mail) else None

        # destinataires
        to, cc, bcc = [], [], []
        rec = msg.recipients
        for k in range(rec.get_number_of_recipients() if rec is not None else 0):
            rp = _props([rec.get_recipient(k)])
            addr = _real_email(_s(rp.get(PR_SMTP_ADDRESS))) or _real_email(_s(rp.get(PR_EMAIL_ADDRESS)))
            a = RawAddress(_s(rp.get(PR_DISPLAY_NAME)), addr)
            {2: cc, 3: bcc}.get(_i(rp.get(PR_RECIPIENT_TYPE)), to).append(a)

        # date : libpff renvoie du naïf UTC
        sent = None
        for getter in (msg.get_client_submit_time, msg.get_delivery_time):
            try:
                sent = getter()
            except Exception:  # noqa: BLE001
                sent = None
            if sent:
                break
        if not isinstance(sent, datetime):
            sent = None

        plain = html = rtf = None
        try:
            plain = decode_body(msg.get_plain_text_body(), *hints)
        except Exception:  # noqa: BLE001
            pass
        try:
            html = decode_body(msg.get_html_body(), *hints)
        except Exception:  # noqa: BLE001
            pass
        has_rtf = False
        try:
            rtf = msg.get_rtf_body()
            has_rtf = bool(rtf)
        except Exception:  # noqa: BLE001
            pass
        if not plain and not html and rtf:
            plain = rtf_to_text(rtf, self._codepage or "cp1252")

        atts = []
        for a in range(msg.get_number_of_attachments()):
            att = msg.get_attachment(a)
            ap = _props(att.record_sets)
            name = att.get_long_filename() or _s(ap.get(PR_ATTACH_LONG_FILENAME)) \
                or _s(ap.get(PR_ATTACH_FILENAME)) or _s(ap.get(PR_DISPLAY_NAME))
            mime = _s(ap.get(PR_ATTACH_MIME_TAG)) or (mimetypes.guess_type(name or "")[0])
            cid = _s(ap.get(PR_ATTACH_CONTENT_ID))
            atts.append(RawAttachment(
                index=a, filename=name, mime=mime, size=att.get_size(), content_id=cid,
                is_inline=bool(cid), attach_method=_i(ap.get(PR_ATTACH_METHOD))))

        return RawMessage(
            ref=ref, folder_path=path,
            message_id=_s(p.get(PR_INTERNET_MESSAGE_ID)) or (str(parsed["Message-ID"]) if parsed and parsed["Message-ID"] else None),
            subject=subject, sender=sender, to=tuple(to), cc=tuple(cc), bcc=tuple(bcc),
            sent_at=sent, date_valid=sent is not None,
            body_text=plain, body_html=html, has_rtf=has_rtf, headers=headers,
            attachments=tuple(atts), message_class=cls,
        )

    # -- pièces jointes --------------------------------------------------------
    def open_attachment(self, message_ref: str, index: int) -> BinaryIO:
        idx, _, n = message_ref.partition(":")
        idx_path = tuple(int(x) for x in idx.split(".")) if idx else ()
        msg = self._folder_at(idx_path).get_sub_message(int(n))
        att = msg.get_attachment(index)
        return io.BufferedReader(_AttachmentStream(att))
