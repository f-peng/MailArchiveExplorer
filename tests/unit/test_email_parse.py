from mail_archive_explorer.readers.email_parse import parse_bytes, to_raw_message, walk_attachments, attachment_bytes
from mail_archive_explorer.readers.mbox_reader import MboxReader, scan_offsets

RAW_LATIN1 = (
    b"From: =?ISO-8859-1?Q?Andr=E9_Dupont?= <andre@example.org>\r\n"
    b"To: \"Zo\xc3\xab\" <zoe@example.org>, bob@example.org\r\n"
    b"Subject: =?UTF-8?B?UsOpdW5pb24gZGUgcsOpZmxleGlvbg==?=\r\n"
    b"Date: Tue, 3 Dec 2024 10:00:00 +0100\r\nMessage-ID: <a@b>\r\n"
    b"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=iso-8859-1\r\n"
    b"Content-Transfer-Encoding: quoted-printable\r\n\r\nCaf=E9 cr=E8me\r\n"
)


def test_en_tetes_encodes_et_corps_latin1():
    m = to_raw_message(parse_bytes(RAW_LATIN1), "x", ("d",))
    assert m.subject == "Réunion de réflexion"
    assert m.sender.name == "André Dupont" and m.sender.email == "andre@example.org"
    assert [a.email for a in m.to] == ["zoe@example.org", "bob@example.org"]
    assert m.body_text.strip() == "Café crème"
    assert str(m.sent_at) == "2024-12-03 09:00:00"          # converti en UTC


def test_pj_nom_encode_et_alternative_html():
    raw = (b"From: a@x.org\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: multipart/mixed; boundary=B\r\n\r\n--B\r\n"
           b"Content-Type: multipart/alternative; boundary=C\r\n\r\n--C\r\nContent-Type: text/plain\r\n\r\ntexte\r\n"
           b"--C\r\nContent-Type: text/html\r\n\r\n<p>html</p>\r\n--C--\r\n--B\r\n"
           b"Content-Type: application/pdf; name=\"=?UTF-8?Q?r=C3=A9sum=C3=A9.pdf?=\"\r\n"
           b"Content-Disposition: attachment; filename=\"=?UTF-8?Q?r=C3=A9sum=C3=A9.pdf?=\"\r\n"
           b"Content-Transfer-Encoding: base64\r\n\r\nSGVsbG8=\r\n--B--\r\n")
    msg = parse_bytes(raw)
    m = to_raw_message(msg, "x", ())
    assert m.body_text.strip() == "texte" and "<p>html</p>" in m.body_html
    assert [(a.filename, a.size) for a in m.attachments] == [("résumé.pdf", 5)]
    assert attachment_bytes(walk_attachments(msg)[0][1]) == b"Hello"


def test_mbox_offsets_et_acces_direct(tmp_path):
    p = tmp_path / "m.mbox"
    parts = []
    for i in range(5):
        parts.append(f"From a@x Mon Jan  1 00:00:00 2020\nSubject: s{i}\nContent-Type: text/plain\n\ncorps {i}\n\nFrom ligne dans le corps\n\n".encode())
    p.write_bytes(b"".join(parts))
    offs = list(scan_offsets(p))
    assert len(offs) == 5
    with MboxReader(p) as r:
        msgs = list(r.iter_messages(next(r.list_folders())))
        assert [m.subject for m in msgs] == [f"s{i}" for i in range(5)]
        again = to_raw_message(parse_bytes(r._read(msgs[3].ref)), "x", ())
        assert again.subject == "s3"


def test_en_tetes_8bits_bruts_pas_de_substituts():
    """Régression trouvée par l'auto-test du paquet : « Subject: Café » non encodé (UTF-8 brut)."""
    raw = ("From: Zoé <zoe@x.org>\nTo: «Élodie» <e@x.org>\nSubject: Café test\nMessage-ID: <é@x>\n"
           "Content-Type: text/plain; charset=utf-8\n\ncorps\n").encode("utf-8")
    m = to_raw_message(parse_bytes(raw), "x", ())
    assert m.subject == "Café test" and m.sender.name == "Zoé" and m.to[0].name == "«Élodie»"
    for text in (m.subject, m.sender.name, m.headers, m.message_id):
        text.encode("utf-8")                       # ne doit jamais lever
    latin = b"Subject: Caf\xe9\nFrom: a@x.org\n\nx\n"
    assert to_raw_message(parse_bytes(latin), "x", ()).subject == "Café"
