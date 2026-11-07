from datetime import datetime

import pytest

from mail_archive_explorer.core.database import backup, open_database, schema_version
from mail_archive_explorer.core.models import RawAddress, RawMessage
from mail_archive_explorer.core.query_parser import QueryError, parse_query
from mail_archive_explorer.services.attachment_service import safe_destination, sanitize_filename
from mail_archive_explorer.services.hashing import clean_subject, content_hash


def _msg(**kw):
    base = dict(ref="1", folder_path=("a",), message_id="<X@Y>", subject="Re: Hello", sender=RawAddress("A", "A@X.org"),
                to=(RawAddress(None, "b@x.org"), RawAddress(None, "c@x.org")), sent_at=datetime(2020, 1, 1, 10, 30, 45),
                body_text="Bonjour\r\n  monde")
    base.update(kw)
    return RawMessage(**base)


def test_content_hash_normalisation():
    a = _msg()
    b = _msg(subject="FWD: RE: hello", sender=RawAddress("Autre", "a@x.org"), to=(RawAddress(None, "C@x.org"), RawAddress(None, "B@x.org")),
             sent_at=datetime(2020, 1, 1, 10, 30, 5), body_text="Bonjour monde ")
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash(_msg(body_text="autre"))
    assert clean_subject("Re: RE: Fwd: Sujet") == "sujet"


def test_content_hash_sans_date_ni_expediteur():
    h = content_hash(_msg(sent_at=None, sender=None, message_id=None))
    assert len(h) == 64


def test_migrations_et_user_version(tmp_path):
    c = open_database(tmp_path / "x.db")
    assert schema_version(c) == 2
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()
    c = open_database(tmp_path / "x.db")  # idempotent
    assert schema_version(c) == 2


def test_backup_restaurable(db, tmp_path):
    db.execute("INSERT INTO archives(path,kind,size,mtime,fingerprint) VALUES('p','mbox',1,1,'f')")
    backup(db, tmp_path / "b.db")
    c = open_database(tmp_path / "b.db")
    assert c.execute("SELECT count(*) FROM archives").fetchone()[0] == 1


@pytest.mark.parametrize("q", ["", "   "])
def test_requete_vide_ok(q):
    assert parse_query(q).fts is None


@pytest.mark.parametrize("q", ["(", "a OR", "NOT", "NOT NOT a", "subject:", "((a)", '"', "***", "a )"])
def test_requetes_malformees_erreur_claire(q):
    with pytest.raises(QueryError):
        parse_query(q)


@pytest.mark.parametrize("q", ['x" OR 1=1 --', "a' ; DROP TABLE messages", "col:val", "NEAR(a b)", "a*b", '"' * 3 + "a"])
def test_requetes_hostiles_ne_levent_pas_dans_fts(db, q):
    from mail_archive_explorer.core.search import search
    try:
        search(db, q)
    except QueryError:
        pass  # acceptable : message clair. Une erreur sqlite3 ne l'est pas.


def test_filtres_dates():
    pq = parse_query("foo before:2020-05-01 after:2020-01-01 has:attachment")
    assert (pq.fts, pq.date_from, pq.date_to, pq.has_attachments) == ('"foo"', "2020-01-01", "2020-05-01", True)
    with pytest.raises(QueryError):
        parse_query("before:demain")


@pytest.mark.parametrize("name,expect", [
    ("../../etc/passwd", "passwd"), ("..", "piece_jointe"), ("C:\\Windows\\x.exe", "x.exe"),
    ("CON.txt", "_CON.txt"), ("a<b>c?.pdf", "a_b_c_.pdf"), (None, "piece_jointe"), ("   ", "piece_jointe"),
])
def test_sanitize(name, expect):
    got = sanitize_filename(name)
    assert "/" not in got and "\\" not in got and got not in ("", ".", "..")
    if name in ("..", None, "   ", "CON.txt", "a<b>c?.pdf"):
        assert got == expect


def test_sanitize_longueur():
    assert len(sanitize_filename("x" * 500 + ".pdf")) <= 125


def test_destination_anti_traversee_et_lien_symbolique(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    (tmp_path / "secret").write_text("s")
    (dest / "evil.txt").symlink_to(tmp_path / "secret")
    p = safe_destination(dest, "evil.txt")
    assert p.parent == dest.resolve() and p.name == "evil (1).txt"
    p2 = safe_destination(dest, "../../x.txt")
    assert p2.parent == dest.resolve()


def test_decode_utf8_mal_etiquete_et_repli():
    from mail_archive_explorer.core.charset import decode_body
    assert decode_body("Zoé café".encode("utf-8"), 28591, 1252) == "Zoé café"     # étiqueté latin-1 mais UTF-8
    assert decode_body("café".encode("cp1252"), 1252) == "café"                      # vrai cp1252
    assert decode_body(b"\xff\xfe", None) is not None                               # jamais d'exception
    assert decode_body("é".encode("utf-16-le"), 1200) == "é"
