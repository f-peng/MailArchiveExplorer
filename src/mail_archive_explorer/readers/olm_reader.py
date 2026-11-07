"""Lecteur OLM (archive Outlook for Mac) : ZIP contenant un XML par message.

Structure observée sur un vrai fichier (voir « Limites connues » du README) :
  Accounts/<compte>/com.microsoft.__Messages/<dossier>/message_NNNNN.xml   (un <email> par fichier)
  Local/com.microsoft.__Messages/<dossier>/...
  <dossier>/com.microsoft.__Attachments/<fichier>   (contenu, référencé par OPFAttachmentURL)
Les dossiers Calendar, Tasks, Notes, Contacts ne sont pas lus (hors périmètre courriel).
"""
from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator

from ..core.models import FolderInfo, RawAddress, RawAttachment, RawMessage, ReadError
from .html_text import html_to_text

MSG_MARK = "com.microsoft.__Messages/"
ATT_DIR = "com.microsoft.__Attachments"
MAX_XML_BYTES = 50 * 1024 * 1024     # un message XML décompressé au-delà de cette taille est refusé (bombe ZIP)


def _txt(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    v = child.text.strip()
    return v or None


def _addresses(el: ET.Element, tag: str) -> tuple[RawAddress, ...]:
    box = el.find(tag)
    if box is None:
        return ()
    out = []
    for a in box.findall("emailAddress"):
        addr = a.get("OPFContactEmailAddressAddress") or None
        name = a.get("OPFContactEmailAddressName") or None
        if addr or name:
            out.append(RawAddress(name, addr))
    return tuple(out)


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _locale_float(value: str | None) -> int | None:
    """OPFAttachmentContentFileSize est écrit avec la virgule décimale locale (« 4,56985E5 »)."""
    if not value:
        return None
    try:
        n = int(float(value.replace(",", ".")))
    except (ValueError, OverflowError):      # « nan », « 1e999 »...
        return None
    return n if 0 <= n < 2**53 else None      # valeurs absurdes (« 1E30 ») ignorées


class OlmReader:
    name = "olm"
    reader_version = "olm-1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zip: zipfile.ZipFile | None = None
        self._folders: dict[tuple[str, ...], list[str]] = {}

    def open(self) -> None:
        if not zipfile.is_zipfile(self.path):
            raise ValueError("Fichier OLM invalide : ce n'est pas une archive ZIP.")
        self._zip = zipfile.ZipFile(self.path, "r")   # lecture seule

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self): self.open(); return self
    def __exit__(self, *exc): self.close()

    @staticmethod
    def _split(member: str) -> tuple[str, tuple[str, ...]] | None:
        """(compte, chemin de dossier) d'un fichier message ; None si ce n'est pas un message."""
        if MSG_MARK not in member or not member.endswith(".xml") or ATT_DIR in member:
            return None
        head, _, tail = member.partition(MSG_MARK)
        parts = tail.split("/")
        if len(parts) < 2:
            return None
        account = head.rstrip("/").split("/")[-1] if head.startswith("Accounts/") else "Local"
        return account, tuple(parts[:-1])

    def list_folders(self) -> Iterator[FolderInfo]:
        groups: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
        for info in self._zip.infolist():
            s = self._split(info.filename)
            if s:
                groups[s].append(info.filename)
        accounts = {a for a, _ in groups}
        self._folders = {}
        for (account, fpath), members in sorted(groups.items()):
            key = (account, *fpath) if len(accounts) > 1 else fpath
            self._folders[key] = sorted(members)
            yield FolderInfo(key, len(members))

    def iter_messages(self, folder: FolderInfo) -> Iterator[RawMessage | ReadError]:
        if not self._folders:
            list(self.list_folders())
        for member in self._folders[folder.path]:
            try:
                yield self._convert(member, folder.path)
            except Exception as exc:  # noqa: BLE001
                yield ReadError(member, folder.path, "parse", type(exc).__name__, str(exc)[:200])

    def _email(self, member: str) -> ET.Element:
        info = self._zip.getinfo(member)
        if info.file_size > MAX_XML_BYTES:
            raise ValueError(f"XML trop volumineux ({info.file_size // 1_000_000} Mo décompressés) : refusé")
        data = self._zip.read(member)
        if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data[:65536].upper():
            raise ValueError("DOCTYPE/ENTITY interdits dans un message OLM")
        root = ET.fromstring(data)
        em = root.find("email") if root.tag == "emails" else root
        if em is None:
            raise ValueError("élément <email> absent")
        return em

    def _convert(self, member: str, path: tuple[str, ...]) -> RawMessage:
        em = self._email(member)
        html_body = _txt(em, "OPFMessageCopyHTMLBody")
        plain = _txt(em, "OPFMessageCopyBody")
        has_html = _txt(em, "OPFMessageGetHasHTML") not in (None, "0E0", "0")
        if html_body and not has_html and "<" not in html_body:
            html_body = None
        if html_body:
            text = html_to_text(html_body)
        else:
            text = plain
        from_ = _addresses(em, "OPFMessageCopyFromAddresses") or _addresses(em, "OPFMessageCopySenderAddress")
        to = _addresses(em, "OPFMessageCopyToAddresses")
        if not to and (dn := _txt(em, "OPFMessageCopyDisplayTo")):
            to = (RawAddress(dn, None),)          # réponses de réunion : seul DisplayTo existe
        sent = _date(_txt(em, "OPFMessageCopySentTime")) or _date(_txt(em, "OPFMessageCopyReceivedTime"))
        atts = []
        al = em.find("OPFMessageCopyAttachmentList")
        if al is not None:
            for i, a in enumerate(al):
                url = a.get("OPFAttachmentURL")
                size = None
                if url:
                    try:
                        size = self._zip.getinfo(url).file_size
                    except KeyError:
                        pass
                if size is None:
                    size = _locale_float(a.get("OPFAttachmentContentFileSize"))
                cid = a.get("OPFAttachmentContentID")
                atts.append(RawAttachment(index=i, filename=a.get("OPFAttachmentName") or None,
                                          mime=a.get("OPFAttachmentContentType") or None, size=size,
                                          content_id=cid,
                                          is_inline=bool(cid) and (a.get("OPFAttachmentContentType") or "").startswith("image/")))
        subject = _txt(em, "OPFMessageCopySubject")
        if not text and (prev := _txt(em, "OPFMessageCopyPreview")):
            text = prev                           # réponses de réunion : seul l'aperçu existe
        is_calendar = _txt(em, "OPFMessageIsCalendarMessage") == "1"
        empty = not (subject or text or from_ or to or atts or is_calendar)
        return RawMessage(
            ref=member, folder_path=path, message_id=_txt(em, "OPFMessageCopyMessageID"),
            subject=subject,
            sender=from_[0] if from_ else None, to=to,
            cc=_addresses(em, "OPFMessageCopyCCAddresses"), bcc=_addresses(em, "OPFMessageCopyBCCAddresses"),
            sent_at=sent, date_valid=sent is not None,
            body_text=text, body_html=html_body, attachments=tuple(atts),
            message_class="IPM.Empty" if empty else "IPM.Note",   # IPM.Empty : métadonnées seules, aucun contenu
        )

    def open_attachment(self, message_ref: str, index: int) -> BinaryIO:
        """Flux sur le contenu. Lève FileNotFoundError si l'archive ne contient pas les octets
        (cas constaté pour la plupart des images incorporées)."""
        em = self._email(message_ref)
        al = em.find("OPFMessageCopyAttachmentList")
        if al is None or index >= len(al):
            raise IndexError(index)
        url = al[index].get("OPFAttachmentURL")
        if not url:
            raise FileNotFoundError("Contenu de la pièce jointe absent de l'archive OLM.")
        return self._zip.open(url)
