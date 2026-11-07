"""Régressions issues de l'audit de sécurité indépendant (F2-F5, F8, F11, F13, F14, F16)."""
import io
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from make_fixtures import make_message, write_eml_dir, write_mbox
from mail_archive_explorer.core.archive_manager import ReaderCache
from mail_archive_explorer.core.database import open_database
from mail_archive_explorer.core.query_parser import QueryError, parse_query
from mail_archive_explorer.core.search import Filters, search
from mail_archive_explorer.readers.olm_reader import MAX_XML_BYTES, OlmReader, _locale_float
from mail_archive_explorer.services.export_service import _ctype, collect_ids, export_eml
from mail_archive_explorer.services.import_service import import_archive

XML = ('<emails><email><OPFMessageCopySubject>{subj}</OPFMessageCopySubject>'
       '<OPFMessageCopyBody>corps {subj}</OPFMessageCopyBody>'
       '<OPFMessageCopySentTime>2024-01-01T10:00:00</OPFMessageCopySentTime>{extra}</email></emails>')
ATT = '<OPFMessageCopyAttachmentList><messageAttachment OPFAttachmentName="x.pdf" OPFAttachmentContentFileSize="{size}"/></OPFMessageCopyAttachmentList>'


def make_olm(path, messages: list[str], extra_members=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, xml in enumerate(messages):
            z.writestr(f"Local/com.microsoft.__Messages/Inbox/message_{i:05d}.xml", xml)
        for n, d in (extra_members or {}).items():
            z.writestr(n, d)
    return path


# F2 -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("v", ["1E30", "1e999", "nan", "-5", "inf", "abc", ""])
def test_f2_tailles_absurdes_ignorees(v):
    assert _locale_float(v) is None
    assert _locale_float("4,5E3") == 4500


def test_f2_olm_taille_absurde_n_avorte_pas_l_import(db, tmp_path):
    olm = make_olm(tmp_path / "a.olm", [XML.format(subj="sain", extra=""),
                                        XML.format(subj="piege", extra=ATT.format(size="1E30")),
                                        XML.format(subj="apres", extra=ATT.format(size="1e999"))])
    r = import_archive(db, olm)
    assert r.imported == 3 and r.errors == 0


# F3 -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("charset", ["unicode_escape", "raw_unicode_escape", "hex", "rot_13", "zlib", "punycode", "nonexistent-xyz"])
def test_f3_charset_malveillant_n_avorte_pas_l_import(db, tmp_path, charset):
    d = tmp_path / "e"
    d.mkdir()
    (d / "1.eml").write_bytes(f"From: a@x.org\nSubject: s\nContent-Type: text/plain; charset={charset}\n\n\\ud800 \xe9\xff\\x00 corps\n".encode("latin-1"))
    (d / "2.eml").write_bytes(b"From: b@x.org\nSubject: apres\n\nok\n")
    r = import_archive(db, d)
    assert r.imported == 2 and r.errors == 0
    assert db.execute("SELECT count(*) FROM messages WHERE subject='apres'").fetchone()[0] == 1


def test_f3_un_message_defectueux_ne_perd_pas_le_lot(db, tmp_path, monkeypatch):
    from mail_archive_explorer.services import import_service as svc
    real = svc._insert_message
    calls = {"n": 0}

    def flaky(conn, a, f, msg):
        calls["n"] += 1
        if calls["n"] == 3:
            conn.execute("INSERT INTO message_bodies(message_id, body_html) VALUES (999999, NULL)")   # violation de clé étrangère
        return real(conn, a, f, msg)
    monkeypatch.setattr(svc, "_insert_message", flaky)
    r = import_archive(db, write_mbox(tmp_path / "m.mbox", 6))
    assert r.imported == 5 and r.errors == 1
    assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 5
    db.execute("INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')")


# F4 -------------------------------------------------------------------------------------------
def test_f4_olm_xml_geant_refuse_sans_charger(db, tmp_path):
    big = "<emails><email>" + "A" * (MAX_XML_BYTES + 1000) + "</email></emails>"
    olm = make_olm(tmp_path / "b.olm", [XML.format(subj="ok", extra=""), big, XML.format(subj="ok2", extra="")])
    assert olm.stat().st_size < 1_000_000                       # la « bombe » est minuscule compressée
    r = import_archive(db, olm)
    assert r.imported == 2 and r.errors == 1 and "trop volumineux" in r.error_samples[0]


def test_f4_olm_doctype_refuse(db, tmp_path):
    evil = '<!DOCTYPE x [<!ENTITY a "aaaa">]><emails><email><OPFMessageCopySubject>&a;</OPFMessageCopySubject></email></emails>'
    r = import_archive(db, make_olm(tmp_path / "c.olm", [evil, XML.format(subj="ok", extra="")]))
    assert r.imported == 1 and r.errors == 1


def test_olm_zipslip_url_ne_sort_pas_de_l_archive(db, tmp_path):
    att = '<OPFMessageCopyAttachmentList><messageAttachment OPFAttachmentName="x" OPFAttachmentURL="../../etc/passwd"/></OPFMessageCopyAttachmentList>'
    olm = make_olm(tmp_path / "d.olm", [XML.format(subj="z", extra=att)])
    with OlmReader(olm) as r:
        folder = next(r.list_folders())
        m = next(iter(r.iter_messages(folder)))
        with pytest.raises(KeyError):                            # membre inexistant dans le ZIP, jamais le disque
            r.open_attachment(m.ref, 0)


# F5 -------------------------------------------------------------------------------------------
def test_f5_mbox_sans_saut_de_ligne_memoire_bornee(tmp_path):
    import tracemalloc
    from mail_archive_explorer.readers.mbox_reader import scan_offsets
    p = tmp_path / "x.mbox"
    p.write_bytes(b"From a@x Mon Jan  1 00:00:00 2024\nSubject: s\n\n" + b"A" * 40_000_000)
    tracemalloc.start()
    offs = list(scan_offsets(p))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(offs) == 1 and peak < 5_000_000, peak


def test_f5_mbox_message_geant_refuse(db, tmp_path, monkeypatch):
    from mail_archive_explorer.readers import mbox_reader
    monkeypatch.setattr(mbox_reader, "MAX_MESSAGE_BYTES", 2000)
    p = tmp_path / "m.mbox"
    p.write_bytes(b"From a@x Mon Jan  1 00:00:00 2024\nSubject: petit\n\nok\n\nFrom a@x Mon Jan  1 00:00:00 2024\nSubject: gros\n\n" + b"B" * 5000 + b"\n\n")
    r = import_archive(db, p)
    assert r.imported == 1 and r.errors == 1


def test_mbox_coupure_au_milieu_d_une_ligne_longue(tmp_path):
    """Un « From » placé juste après un morceau de 64 Ko n'est pas un séparateur."""
    from mail_archive_explorer.readers.mbox_reader import scan_offsets
    p = tmp_path / "y.mbox"
    p.write_bytes(b"From a@x Mon Jan  1 00:00:00 2024\nSubject: s\n\n" + b"x" * 65536 + b"From b@x Mon Jan  1 00:00:00 2024\n\nfin\n")
    assert len(list(scan_offsets(p))) == 1


# F8 -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["dossier#1", "a?b", "50%20x", "espace et é"])
def test_f8_chemin_special_base(tmp_path, name):
    if sys.platform == "win32" and "?" in name:
        pytest.skip("« ? » est interdit dans un nom de dossier Windows")
    d = tmp_path / name
    c = open_database(d / "archive.db")
    c.execute("INSERT INTO archives(path,kind,size,mtime,fingerprint) VALUES('p','mbox',1,1,'f')")
    c.close()
    assert (d / "archive.db").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]    # aucun fichier tronqué créé à côté
    assert open_database(d / "archive.db").execute("SELECT count(*) FROM archives").fetchone()[0] == 1


# F11 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("q", ["(" * 5000, "a " * 5000, "x" * 5000])
def test_f11_requetes_demesurees_donnent_queryerror(db, q):
    with pytest.raises(QueryError):
        search(db, q)


@pytest.mark.parametrize("q", ["from:(subject:x)", "a\x00b", "subject:(from:(to:a))", "{subject}: a", "NEAR(a b)", "a ** b", "\\", "'\"`"])
def test_f11_jamais_d_erreur_sql_brute(db, q):
    try:
        search(db, q)
    except QueryError:
        pass                                    # message clair : accepté ; toute autre exception échoue le test


def test_f11_tri_inconnu():
    with pytest.raises(ValueError):
        search(sqlite3.connect(":memory:"), "", sort="id; DROP TABLE messages")


# F13 ------------------------------------------------------------------------------------------
def test_f13_symlink_eml_ignore(db, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("From: a@x.org\nSubject: TOPSECRET\n\nTOPSECRET-LINE\n")
    d = write_eml_dir(tmp_path / "e", 2)
    (d / "Inbox" / "piege.eml").symlink_to(secret)
    (d / "lien_dossier").symlink_to(tmp_path)
    r = import_archive(db, d)
    assert r.imported == 2 and r.errors == 1
    assert "symbolique" in r.error_samples[0]
    assert not search(db, "TOPSECRET").hits


# F14 / F16 ------------------------------------------------------------------------------------
def test_f14_export_eml_ne_suit_pas_un_lien(db, tmp_path):
    import_archive(db, write_mbox(tmp_path / "s.mbox", 1))
    ids = collect_ids(db, "", Filters())
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victime.txt"
    victim.write_text("intact")
    row = db.execute("SELECT m.*, a.kind a_kind, a.path a_path, a.engine a_engine FROM messages m JOIN archives a ON a.id=m.archive_id").fetchone()
    from mail_archive_explorer.services.export_service import _name_for
    (out / _name_for(row)).symlink_to(victim)
    rep = export_eml(db, ids, out, ReaderCache())
    assert rep.written == 1 and victim.read_text() == "intact"


@pytest.mark.parametrize("mime,expected", [
    ("application/pdf", ("application", "pdf")), ("a/b; boundary=x", ("application", "octet-stream")),
    ("text/plain\r\nBcc: evil@x.org", ("application", "octet-stream")), (None, ("application", "octet-stream")),
    ("../../x", ("application", "octet-stream")),
])
def test_f16_mime_valide(mime, expected):
    assert _ctype(mime) == expected


def test_f16_content_id_avec_crlf_n_empeche_pas_l_export(db, tmp_path):
    d = tmp_path / "olm"
    olm = make_olm(tmp_path / "f.olm", [XML.format(subj="cid", extra=(
        '<OPFMessageCopyAttachmentList><messageAttachment OPFAttachmentName="i.png" OPFAttachmentContentType="image/png&#13;&#10;X: y" '
        'OPFAttachmentContentID="a&#13;&#10;Bcc: evil@x.org" OPFAttachmentURL="Local/com.microsoft.__Messages/Inbox/com.microsoft.__Attachments/f"/></OPFMessageCopyAttachmentList>'))],
        {"Local/com.microsoft.__Messages/Inbox/com.microsoft.__Attachments/f": b"\x89PNG"})
    import_archive(db, olm)
    rep = export_eml(db, collect_ids(db, "", Filters()), tmp_path / "o", ReaderCache())
    assert rep.written == 1 and rep.skipped == 0
    raw = next((tmp_path / "o").glob("*.eml")).read_bytes()
    assert b"evil@x.org" not in raw.split(b"\r\n\r\n", 1)[0]       # rien dans les en-têtes
