import csv
import email
import threading
from email import policy
from pathlib import Path

import pytest

from conftest import pst_file
from make_fixtures import make_message, write_eml_dir, write_mbox
from mail_archive_explorer.core.archive_manager import ReaderCache
from mail_archive_explorer.core.search import Filters, search
from mail_archive_explorer.services.export_service import (collect_ids, csv_safe, export_attachments, export_csv,
                                                           export_eml, export_mbox)
from mail_archive_explorer.services.import_service import import_archive


@pytest.fixture
def readers():
    r = ReaderCache()
    yield r
    r.close_all()


def ids_of(db, q=""):
    return collect_ids(db, q, Filters())


def test_eml_mbox_exporte_octets_d_origine(db, tmp_path, readers):
    mb = write_mbox(tmp_path / "s.mbox", 6, html=True, attachment=("p.pdf", b"%PDF"))
    import_archive(db, mb)
    out = tmp_path / "eml"
    rep = export_eml(db, ids_of(db), out, readers)
    assert rep.written == 6 and not rep.errors
    files = sorted(out.glob("*.eml"))
    assert len(files) == 6
    m = email.message_from_bytes(files[0].read_bytes(), policy=policy.default)
    assert m["Subject"].startswith("Réunion numéro") and m.get_body(("plain",)).get_content().startswith("Bonjour")
    assert [p.get_filename() for p in m.iter_attachments()] == ["p.pdf"]
    from mail_archive_explorer.readers.mbox_reader import scan_offsets
    original = mb.read_bytes()
    off, length = next(iter(scan_offsets(mb)))
    first = db.execute("SELECT id FROM messages WHERE source_ref=?", (f"{off}:{length}",)).fetchone()["id"]
    out2 = tmp_path / "one"
    export_eml(db, [first], out2, readers)
    assert next(out2.glob("*.eml")).read_bytes() == original[off:off + length]      # octets identiques


def test_pst_eml_reconstruit(db, tmp_path, readers):
    import_archive(db, pst_file("tika_testPST.pst"))
    out = tmp_path / "eml"
    rep = export_eml(db, ids_of(db, "tokenizer"), out, readers)
    assert rep.written == 1
    m = email.message_from_bytes(next(out.glob("*.eml")).read_bytes(), policy=policy.default)
    assert "tokenizer" in m["Subject"] and m["From"] and m["To"] and m["Date"] and m["Message-ID"]
    assert "tokenizer" in m.get_body(("plain",)).get_content().lower()
    rep2 = export_eml(db, ids_of(db, "filename:email"), tmp_path / "eml2", readers)
    pj = email.message_from_bytes(next((tmp_path / "eml2").glob("*.eml")).read_bytes(), policy=policy.default)
    assert len(list(pj.iter_attachments())) == 1


def test_mbox_aller_retour(db, tmp_path, readers):
    import_archive(db, pst_file("tika_testPST.pst"))
    mb = tmp_path / "out.mbox"
    rep = export_mbox(db, ids_of(db), mb, readers)
    assert rep.written == 7
    with pytest.raises(FileExistsError):               # ne remplace jamais un fichier
        export_mbox(db, ids_of(db), mb, readers)
    from mail_archive_explorer.core.database import open_database
    c2 = open_database(tmp_path / "second.db", bulk=True)
    r = import_archive(c2, mb)
    assert r.imported == 7 and r.errors == 0
    a = sorted(x[0] for x in db.execute("SELECT subject FROM messages"))
    b = sorted(x[0] for x in c2.execute("SELECT subject FROM messages"))
    assert a == b
    assert search(c2, "tokenizer").hits


def test_mbox_echappement_from(db, tmp_path, readers):
    m = make_message(1)
    m.set_content("ligne\n\nFrom quelqu'un a ecrit\n>From deja cite\n")
    d = tmp_path / "e"
    d.mkdir()
    (d / "1.eml").write_bytes(bytes(m))
    import_archive(db, d)
    mb = tmp_path / "o.mbox"
    export_mbox(db, ids_of(db), mb, readers)
    raw = mb.read_bytes()
    assert b"\n>From quelqu'un" in raw and b"\n>>From deja cite" in raw
    from mail_archive_explorer.readers.mbox_reader import scan_offsets
    assert len(list(scan_offsets(mb))) == 1


def test_csv_complet_bom_et_injection(db, tmp_path):
    d = tmp_path / "e"
    d.mkdir()
    for i in range(1500):                                     # > taille de page : tout doit sortir
        m = make_message(i)
        del m["Subject"]
        m["Subject"] = "=HYPERLINK(\"http://x\")" if i == 0 else f"objet {i}"
        (d / f"{i}.eml").write_bytes(bytes(m))
    import_archive(db, d)
    dest = tmp_path / "res.csv"
    rep = export_csv(db, "", Filters(), dest)
    assert rep.written == 1500
    raw = dest.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter=";"))
    assert len(rows) == 1501 and rows[0][0] == "Date (UTC)"
    assert not any(r[3].startswith(("=", "+", "-", "@")) for r in rows[1:])
    assert any(r[3].startswith("'=HYPERLINK") for r in rows[1:])
    assert csv_safe("-2+3") == "'-2+3" and csv_safe("normal") == "normal" and csv_safe(None) == ""
    with pytest.raises(FileExistsError):
        export_csv(db, "", Filters(), dest)


def test_pj_export_noms_dangereux_et_sous_dossiers(db, tmp_path, readers):
    d = write_eml_dir(tmp_path / "e", 3, attachment=("../../evil.sh", b"echo"))
    import_archive(db, d)
    out = tmp_path / "pj"
    rep = export_attachments(db, ids_of(db), out, readers)
    assert rep.written == 3 and not rep.errors
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) == 3 and all(out.resolve() in p.resolve().parents for p in files)


def test_annulation_et_erreur_isolee(db, tmp_path, readers):
    import_archive(db, write_mbox(tmp_path / "s.mbox", 50))
    ev = threading.Event()
    ev.set()
    rep = export_eml(db, ids_of(db), tmp_path / "x", readers, cancel=ev)
    assert rep.cancelled and rep.written == 0
    rep = export_eml(db, [999999] + ids_of(db)[:3], tmp_path / "y", readers)
    assert rep.written == 3 and rep.skipped == 1


def test_olm_export_eml_et_mbox(db, tmp_path, readers):
    from conftest import pst_file as pf
    import_archive(db, pf("mac_archive.olm"))
    ids = collect_ids(db, "has:attachment", Filters())[:30]
    rep = export_eml(db, ids, tmp_path / "o", readers)
    assert rep.written == len(ids) and rep.skipped == 0       # PJ indisponibles = avertissements, pas échecs
    for f in (tmp_path / "o").glob("*.eml"):
        m = email.message_from_bytes(f.read_bytes(), policy=policy.default)
        assert m["Date"] and m["Message-ID"]
    out_mbox = tmp_path / "o.mbox"
    assert export_mbox(db, ids, out_mbox, readers).written == len(ids)
