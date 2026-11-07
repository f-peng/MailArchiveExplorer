"""Auto-test embarqué : `--selftest`. Vérifie dans l'application PACKAGÉE (ou installée) que les
dépendances natives chargent : pypff, SQLite FTS5, import/recherche, rendu HTML WebEngine."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def run() -> int:
    results: dict[str, str] = {}

    def step(name, fn):
        try:
            results[name] = "OK " + str(fn() or "")
        except Exception as exc:  # noqa: BLE001
            results[name] = f"ECHEC {type(exc).__name__}: {exc}"

    def pypff_check():
        import pypff
        return pypff.get_version()

    def fts_check():
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(a, tokenize='unicode61 remove_diacritics 2')")
        c.execute("INSERT INTO t VALUES ('café')")
        assert c.execute("SELECT count(*) FROM t WHERE t MATCH 'cafe'").fetchone()[0] == 1
        return sqlite3.sqlite_version

    def import_search():
        from .core.database import open_database
        from .core.search import search
        from .services.import_service import import_archive
        d = Path(tempfile.mkdtemp(prefix="mae_selftest_"))
        mbox = d / "t.mbox"
        mbox.write_bytes(b"From a@x Mon Jan  1 00:00:00 2024\nFrom: a@x.org\nSubject: Caf\xc3\xa9 test\n"
                         b"Content-Type: text/plain; charset=utf-8\n\nbonjour licorne\n\n")
        conn = open_database(d / "t.db", bulk=True)
        rep = import_archive(conn, mbox)
        assert rep.imported == 1 and rep.errors == 0, rep
        assert search(conn, "licorne").hits and search(conn, "cafe").hits
        conn.close()
        return "import+recherche"

    def webengine():
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        from .ui.message_viewer import HAVE_WEBENGINE, SafeHtmlView
        assert HAVE_WEBENGINE, "QtWebEngine indisponible"
        view = SafeHtmlView()
        out: list[str] = []
        loop = QEventLoop()
        view.loadFinished.connect(lambda ok: view.page().toPlainText(lambda t: (out.append(t), loop.quit())))
        view.show_html("<p>Bonjour</p><script>document.body.innerText='JS'</script>", False)
        QTimer.singleShot(20000, loop.quit)
        loop.exec()
        view.shutdown()
        assert out and out[0].strip() == "Bonjour", f"rendu inattendu : {out!r}"
        return "rendu HTML, JavaScript désactivé"

    def webengine_isolation():
        """Aucune connexion réseau pour un lien preconnect (régression de l'audit) ; HTML trop gros refusé."""
        import socket
        import threading
        import time
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        from .ui.message_viewer import SafeHtmlView
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(10)
        srv.settimeout(0.2)
        port = srv.getsockname()[1]
        hits: list[int] = []
        stop = threading.Event()

        def accept():
            while not stop.is_set():
                try:
                    c, _ = srv.accept()
                    hits.append(1)
                    c.close()
                except OSError:
                    pass
        t = threading.Thread(target=accept, daemon=True)
        t.start()
        view = SafeHtmlView()
        loop = QEventLoop()
        view.loadFinished.connect(lambda ok: QTimer.singleShot(2000, loop.quit))
        assert view.show_html(f'<html><head><link rel="preconnect" href="http://127.0.0.1:{port}">'
                              f'<link rel="dns-prefetch" href="http://127.0.0.1:{port}"></head><body>x</body></html>', False)
        QTimer.singleShot(15000, loop.quit)
        loop.exec()
        stop.set()
        t.join(1)
        srv.close()
        big = view.show_html("<p>" + "x" * 2_100_000 + "</p>", False)
        view.shutdown()
        assert not hits, f"{len(hits)} connexion(s) réseau sortante(s) !"
        assert big is False, "un HTML > limite de setHtml() aurait dû être refusé"
        return "0 connexion, gros HTML refusé"

    step("pypff", pypff_check)
    step("sqlite_fts5", fts_check)
    step("import_recherche", import_search)
    step("webengine", webengine)
    step("webengine_isolation", webengine_isolation)
    ok = all(v.startswith("OK") for v in results.values())
    lines = [f"{k:18} {v}" for k, v in results.items()] + ["SELFTEST " + ("OK" if ok else "ECHEC")]
    text = "\n".join(lines)
    try:
        print(text)
    except Exception:  # noqa: BLE001 - application « fenêtrée » Windows : pas de stdout
        pass
    out = os.environ.get("MAE_SELFTEST_OUT")        # utile quand il n'y a pas de console (exécutable Windows)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    return 0 if ok else 1
