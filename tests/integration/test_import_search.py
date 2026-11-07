import hashlib
import threading
from pathlib import Path

import pytest

from conftest import pst_file
from make_fixtures import write_eml_dir, write_mbox
from mail_archive_explorer.core import archive_manager
from mail_archive_explorer.core.query_parser import QueryError
from mail_archive_explorer.core.search import Filters, search
from mail_archive_explorer.readers.pst.pypff_engine import PypffEngine
from mail_archive_explorer.readers.pst.readpst_engine import ReadpstEngine
from mail_archive_explorer.services.attachment_service import extract_stream
from mail_archive_explorer.services.import_service import import_archive


def count(db, table="messages"):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def fts_consistent(db):
    db.execute("INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')")
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------- vrais PST ----------
def test_pst_tika_pypff(db):
    p = pst_file("tika_testPST.pst")
    before = sha(p)
    r = import_archive(db, p)
    assert (r.imported, r.errors, r.engine) == (7, 0, "pypff")
    assert sha(p) == before  # source inchangée
    assert db.execute("SELECT count(*) FROM messages WHERE sender LIKE '%@%'").fetchone()[0] >= 6   # adresses SMTP résolues
    assert search(db, "tokenizer").hits
    assert [h.subject for h in search(db, "filename:email").hits] == ["FW: First email"]
    fts_consistent(db)


def test_pst_pj_flux_et_hash(db, tmp_path):
    p = pst_file("tika_testPST.pst")
    import_archive(db, p)
    row = db.execute("SELECT a.idx, a.filename, a.size, m.source_ref FROM attachments a JOIN messages m ON m.id=a.message_id").fetchone()
    with PypffEngine(p) as e:
        out, digest = extract_stream(e.open_attachment(row["source_ref"], row["idx"]), tmp_path, "../../" + row["filename"])
    assert out.parent == tmp_path.resolve() and out.stat().st_size == row["size"] and len(digest) == 64


def test_pst_ost_et_contenu_non_mail(db):
    r = import_archive(db, pst_file("example-2013.ost"))
    assert r.imported == 3 and r.errors == 0
    r2 = import_archive(db, pst_file("dist-list.pst"))
    assert r2.imported == 0 and r2.skipped_non_mail == 4


@pytest.mark.skipif(not ReadpstEngine.is_available(), reason="readpst absent")
def test_pst_repli_readpst(db):
    r = import_archive(db, pst_file("tika_testPST.pst"), engine="readpst")
    assert r.engine == "readpst" and r.imported == 7 and r.errors == 0
    assert search(db, "tokenizer").hits


def test_pst_vide_et_invalide(db, tmp_path):
    empty = tmp_path / "vide.pst"
    empty.write_bytes(b"")
    assert not PypffEngine.probe(empty).valid
    bad = tmp_path / "faux.pst"
    bad.write_bytes(b"ceci n'est pas un pst" * 100)
    assert not PypffEngine.probe(bad).valid
    with pytest.raises(Exception):
        import_archive(db, bad, engine="pypff")
    fts_consistent(db)


def test_pst_tronque_ne_corrompt_pas_la_base(db, tmp_path):
    src = pst_file("tika_testPST.pst").read_bytes()
    t = tmp_path / "tronque.pst"
    t.write_bytes(src[: len(src) // 3])
    try:
        import_archive(db, t, engine="pypff")
    except Exception:
        pass  # échec franc accepté ; l'important est la cohérence
    fts_consistent(db)


def test_idempotence_reimport(db):
    p = pst_file("tika_testPST.pst")
    import_archive(db, p)
    n = count(db)
    import_archive(db, p)
    assert count(db) == n and count(db, "archives") == 1


# ---------- MBOX / EML synthétiques ----------
def test_mbox_et_recherche(db, tmp_path):
    mb = write_mbox(tmp_path / "boite.mbox", 30, html=True, attachment=("rapport 'été'.pdf", b"%PDF-1.4 x"))
    r = import_archive(db, mb)
    assert r.imported == 30 and r.errors == 0
    assert len(search(db, "licorne1").hits) == 10
    assert len(search(db, "cafe").hits) == 30           # sans accent -> "café"
    assert len(search(db, '"ordre du jour 7"').hits) == 1
    assert len(search(db, "licorne1 NOT licorne2").hits) == 10
    assert len(search(db, "has:attachment").hits) == 30
    assert search(db, "pj:rapport").hits
    assert len(search(db, "to:carole").hits) == 30
    p1 = search(db, "", limit=10)
    p2 = search(db, "", after=p1.next_cursor, limit=10)
    assert not ({h.id for h in p1.hits} & {h.id for h in p2.hits}) and len(p2.hits) == 10
    assert p1.hits[0].sent_at > p1.hits[-1].sent_at
    with pytest.raises(QueryError):
        search(db, "(")


def test_eml_dossier_dates_invalides_sans_expediteur(db, tmp_path):
    root = write_eml_dir(tmp_path / "eml", 3, date="pas une date", sender=None)
    r = import_archive(db, root)
    assert r.imported == 3
    row = db.execute("SELECT sent_at, date_valid, sender FROM messages LIMIT 1").fetchone()
    assert row["sent_at"] is None and row["date_valid"] == 0 and row["sender"] is None
    assert len(search(db, "reunion").hits) == 3     # messages sans date toujours trouvables
    p = search(db, "", limit=2)
    assert p.next_cursor.value is None and len(search(db, "", after=p.next_cursor, limit=2).hits) == 1


def test_doublons_conserves_avec_provenance(db, tmp_path):
    a = write_mbox(tmp_path / "a.mbox", 5)
    b = write_mbox(tmp_path / "b.mbox", 5)
    import_archive(db, a)
    import_archive(db, b)
    assert count(db) == 10                                   # jamais de suppression automatique
    dup = db.execute("SELECT content_hash, count(*) c FROM messages GROUP BY content_hash HAVING c>1").fetchall()
    assert len(dup) == 5
    assert count(db, "message_sources") == 10


def test_import_interrompu_puis_repris(db, tmp_path):
    mb = write_mbox(tmp_path / "gros.mbox", 120)
    cancel = threading.Event()

    class Stop:
        def on_folder(self, *a): ...
        def on_progress(self, folder, done, errors):
            if done >= 40:
                cancel.set()

    r1 = import_archive(db, mb, progress=Stop(), cancel=cancel, batch_size=20)
    assert r1.cancelled and 0 < count(db) < 120
    fts_consistent(db)
    r2 = import_archive(db, mb, batch_size=20)
    assert count(db) == 120 and r2.skipped_existing > 0
    assert len(search(db, "licorne0").hits) == 40
    fts_consistent(db)


def test_arret_brutal_rollback_du_lot_en_cours(db, tmp_path, monkeypatch):
    mb = write_mbox(tmp_path / "crash.mbox", 60)
    real = archive_manager.open_reader

    class Boom:
        def __init__(self, inner): self.inner = inner; self.name = "boom"
        def __enter__(self): self.inner.open(); return self
        def __exit__(self, *e): self.inner.close()
        def list_folders(self): return self.inner.list_folders()
        def iter_messages(self, f):
            for i, m in enumerate(self.inner.iter_messages(f)):
                if i == 45:
                    raise RuntimeError("crash simulé")
                yield m

    from mail_archive_explorer.services import import_service
    monkeypatch.setattr(import_service, "open_reader", lambda k, p, e=None: Boom(real(k, p, e)))
    with pytest.raises(RuntimeError):
        import_archive(db, mb, batch_size=20)
    assert count(db) == 40                       # 2 lots validés, le lot partiel est annulé
    fts_consistent(db)
    monkeypatch.undo()
    import_archive(db, mb, batch_size=20)
    assert count(db) == 60
    fts_consistent(db)


def test_source_mbox_inchangee(db, tmp_path):
    mb = write_mbox(tmp_path / "s.mbox", 10)
    before = sha(mb)
    import_archive(db, mb)
    assert sha(mb) == before


def test_filtres_archive_dossier(db, tmp_path):
    import_archive(db, write_mbox(tmp_path / "a.mbox", 4))
    import_archive(db, write_mbox(tmp_path / "b.mbox", 6))
    ids = [r[0] for r in db.execute("SELECT id FROM archives ORDER BY id")]
    assert len(search(db, "", Filters(archive_ids=[ids[1]])).hits) == 6
    assert len(search(db, "", Filters(archive_ids=ids)).hits) == 10
    assert len(search(db, "", Filters(date_from="2020-01-01", date_to="2020-01-01")).hits) == 10


# ---------- OLM : fichier privé réel, jamais dans le dépôt ; aucune valeur personnelle codée ici ----------
def _olm():
    return pst_file("mac_archive.olm")


def test_olm_import_reel(db):
    import zipfile
    p = _olm()
    before = sha(p)
    with zipfile.ZipFile(p) as z:
        n_files = sum(1 for n in z.namelist() if "com.microsoft.__Messages/" in n and n.endswith(".xml") and "__Attachments" not in n)
    r = import_archive(db, p)
    assert r.engine == "olm" and r.errors == 0
    assert r.imported + r.skipped_empty + r.skipped_non_mail == n_files   # rien de perdu silencieusement
    assert r.imported > 0 and count(db) == r.imported
    assert sha(p) == before
    fts_consistent(db)
    # recherche : un mot réel pris dans la base elle-même
    row = db.execute("SELECT subject FROM messages WHERE subject IS NOT NULL AND length(subject) > 15 LIMIT 1").fetchone()
    word = max(row["subject"].split(), key=len).strip(".,:;()[]\"'")
    assert search(db, f'"{word}"').hits


def test_olm_pj_flux(db, tmp_path):
    import_archive(db, _olm())
    row = db.execute("SELECT m.id, m.source_ref, a.idx, a.filename, a.size FROM attachments a JOIN messages m ON m.id=a.message_id "
                     "WHERE a.filename IS NOT NULL AND a.filename LIKE '%.%' LIMIT 300").fetchall()
    from mail_archive_explorer.readers.olm_reader import OlmReader
    ok = 0
    with OlmReader(_olm()) as r:
        for x in row:
            try:
                stream = r.open_attachment(x["source_ref"], x["idx"])
            except FileNotFoundError:
                continue
            out, digest = extract_stream(stream, tmp_path, x["filename"])
            assert out.parent == tmp_path.resolve() and out.stat().st_size == x["size"]
            ok += 1
    assert ok >= 1


def test_olm_invalide(db, tmp_path):
    bad = tmp_path / "faux.olm"
    bad.write_bytes(b"pas un zip")
    with pytest.raises(ValueError):
        import_archive(db, bad)


@pytest.mark.parametrize("sort", ["date", "sender", "subject", "folder", "attachments"])
@pytest.mark.parametrize("desc", [True, False])
def test_tri_et_pagination_keyset(db, tmp_path, sort, desc):
    import_archive(db, write_mbox(tmp_path / "a.mbox", 25, attachment=("x.pdf", b"1")))
    import_archive(db, write_eml_dir(tmp_path / "e", 7, date="invalide", sender=None))
    full = search(db, "", limit=1000, sort=sort, descending=desc)
    paged, cur = [], None
    while True:
        pg = search(db, "", after=cur, limit=6, sort=sort, descending=desc)
        paged += pg.hits
        cur = pg.next_cursor
        if not cur:
            break
    ids = [h.id for h in paged]
    assert ids == [h.id for h in full.hits] and len(ids) == len(set(ids)) == 32   # ni doublon ni trou
    if sort == "date":
        dated = [h.sent_at for h in full.hits if h.sent_at]
        assert dated == sorted(dated, reverse=desc)
    if sort == "subject":
        subs = [(h.subject or "").lower() for h in full.hits]
        assert subs == sorted(subs, reverse=desc)
