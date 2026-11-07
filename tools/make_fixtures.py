"""Génération de fixtures synthétiques MBOX / EML (aucune donnée personnelle)."""
from __future__ import annotations

import mailbox
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path


def make_message(i: int, *, html: bool = False, attachment: tuple[str, bytes] | None = None,
                 date: str | None = "auto", sender: str | None = "alice@example.org") -> EmailMessage:
    m = EmailMessage()
    if sender:
        m["From"] = sender
    m["To"] = "bob@example.org, Carole <carole@example.org>"
    m["Subject"] = f"Réunion numéro {i} café"
    m["Message-ID"] = f"<synthetic-{i}@example.org>"
    if date == "auto":
        m["Date"] = format_datetime(datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i))
    elif date:
        m["Date"] = date
    m.set_content(f"Bonjour, ordre du jour {i}. Mot-clé: licorne{i % 3}.")
    if html:
        m.add_alternative(f"<html><body><p>Bonjour <b>{i}</b></p></body></html>", subtype="html")
    if attachment:
        name, data = attachment
        m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return m


def write_mbox(path: Path, n: int, **kw) -> Path:
    box = mailbox.mbox(str(path))
    try:
        for i in range(n):
            box.add(make_message(i, **kw))
        box.flush()
    finally:
        box.close()
    return path


def write_eml_dir(root: Path, n: int, **kw) -> Path:
    (root / "Inbox").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / "Inbox" / f"{i}.eml").write_bytes(bytes(make_message(i, **kw)))
    return root
