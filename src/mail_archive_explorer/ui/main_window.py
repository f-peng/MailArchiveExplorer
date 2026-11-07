"""Fenêtre principale : arbre, liste, visualiseur, recherche, import."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QFileDialog, QHeaderView, QLineEdit, QMainWindow, QMenu, QToolButton, QMessageBox,
                               QProgressBar, QPushButton, QSplitter, QTableView, QToolBar, QWidget)

from ..core import archive_manager
from ..core.perf import timed
from ..core.database import backup, connect, open_database
from ..core.query_parser import QueryError
from ..core.search import Filters
from ..services.attachment_service import extract_stream
from ..workers.export_worker import ExportWorker
from ..workers.import_worker import ImportWorker
from ..workers.remove_worker import RemoveWorker
from .archive_tree import ArchiveTree
from .dialogs import messages as dialogs
from .message_list import COL_ATT, COL_DATE, COL_FOLDER, COL_FROM, COL_SNIPPET, COL_SUBJECT, COL_TO, COLUMNS, MessageListModel
from .message_viewer import MessageViewer
from .theme import apply_theme, colors, current_theme, stylesheet

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, db_file: Path):
        super().__init__()
        self.setWindowTitle(self.tr("Mail Archive Explorer"))
        self.resize(1400, 850)
        self.db_file = db_file
        open_database(db_file).close()                   # crée / migre
        self.conn = connect(db_file, readonly=True)       # l'UI ne fait que lire
        self.worker: ImportWorker | None = None

        self.tree = ArchiveTree(self.conn)
        self.model = MessageListModel(self.conn)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(COL_DATE, Qt.DescendingOrder)
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        for col, w in ((COL_DATE, 130), (COL_FROM, 150), (COL_TO, 150), (COL_SUBJECT, 300), (COL_ATT, 36), (COL_FOLDER, 120)):
            self.table.setColumnWidth(col, w)
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(COL_ATT, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_SNIPPET, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_SNIPPET, 200)
        hh.sectionClicked.connect(self._header_clicked)
        self.readers = archive_manager.ReaderCache()
        self.viewer = MessageViewer(self.conn, self.readers)

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.table)
        right.addWidget(self.viewer)
        right.setSizes([240, 620])
        main = QSplitter()
        main.addWidget(self.tree)
        main.addWidget(right)
        main.setSizes([250, 1150])
        self.setCentralWidget(main)

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        add = QAction(self.tr("Ajouter une archive…"), self, triggered=self.add_archive)
        self.rm = QAction(self.tr("Décharger l'archive"), self, triggered=self.remove_archive)
        self.rm.setToolTip(self.tr("Retire l'archive sélectionnée de l'index (le fichier source n'est pas modifié)"))
        self.rm.setEnabled(False)
        rm = self.rm
        bk = QAction(self.tr("Sauvegarder la base…"), self, triggered=self.backup_db)
        self.theme_action = QAction(self.tr("Thème sombre"), self, checkable=True,
                                    checked=current_theme() == "dark", triggered=self.toggle_theme)
        for a in (add, rm, bk):
            tb.addAction(a)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(self.tr('Rechercher : mots, "expression", AND OR NOT, from: to: subject: pj: before:AAAA-MM-JJ has:attachment'))
        self.search_box.setClearButtonEnabled(True)
        self._theme_after_search = True
        self.search_box.returnPressed.connect(self.run_search)
        tb.addWidget(self.search_box)
        self.cancel_btn = QPushButton(self.tr("Annuler l'import"))
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self._cancel_current)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        self.export_btn = QToolButton()
        self.export_btn.setText(self.tr("Exporter ▾"))
        self.export_btn.setPopupMode(QToolButton.InstantPopup)
        self.export_menu = self._build_export_menu()
        self.export_btn.setMenu(self.export_menu)
        tb.insertWidget(self.search_box_action, self.export_btn) if hasattr(self, 'search_box_action') else tb.addWidget(self.export_btn)
        tb.addAction(self.theme_action)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)

        self.set_theme(current_theme())
        self.tree.currentItemChanged.connect(lambda *_: (self.rm.setEnabled(self.tree.selected_archive() is not None), self.run_search()))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.table.selectionModel().currentRowChanged.connect(self._row_changed)
        self.viewer.attachment_requested.connect(self.save_attachment)
        self.refresh()

    def set_theme(self, name: str) -> None:
        c = apply_theme(QApplication.instance(), name)
        self.setStyleSheet(stylesheet(c))
        self.viewer.apply_colors(c)

    def toggle_theme(self, dark: bool) -> None:
        self.set_theme("dark" if dark else "light")

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(10000)
        self.viewer.shutdown()
        self.readers.close_all()
        super().closeEvent(event)

    # ----- données -----
    def refresh(self) -> None:
        self.tree.reload()
        self.run_search()

    def _filters(self) -> Filters:
        f = Filters()
        item = self.tree.currentItem()
        if item:
            kind, ident, _aid = item.data(0, ArchiveTree.ROLE)
            if kind == "archive":
                f.archive_ids = [ident]
            elif kind == "folder":
                f.folder_id = ident
        return f

    def _header_clicked(self, col: int) -> None:
        key = COLUMNS[col][1]
        if key is None:
            return
        hh = self.table.horizontalHeader()
        desc = (not self.model.descending) if key == self.model.sort_key else (key == "date")
        hh.setSortIndicator(col, Qt.DescendingOrder if desc else Qt.AscendingOrder)
        self.run_search(sort_key=key, descending=desc)

    def run_search(self, *_, sort_key: str | None = None, descending: bool | None = None) -> None:
        try:
            with timed("recherche/tri"):
                self.model.set_search(self.search_box.text(), self._filters(), sort_key, descending)
            self.table.setColumnHidden(COL_SNIPPET, not self.search_box.text().strip())
            self.statusBar().showMessage(self.tr("{n} résultat(s) chargé(s)").format(n=len(self.model.rows))
                                         + ("+" if not self.model.exhausted else ""))
        except QueryError as exc:
            self.statusBar().showMessage(self.tr("Requête invalide : ") + str(exc), 8000)

    def _row_changed(self, cur, _prev) -> None:
        if cur.isValid():
            with timed("affichage message"):
                self.viewer.show_message(self.model.rows[cur.row()].id)
        else:
            self.viewer.clear()

    # ----- import -----
    def add_archive(self) -> None:
        if self.worker and self.worker.isRunning():
            dialogs.information(self, self.windowTitle(), self.tr("Un import est déjà en cours."))
            return
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Choisir une archive"), "",
                                              self.tr("Archives (*.pst *.ost *.olm *.mbox *.eml);;Tous les fichiers (*)"))
        if not path:
            return
        self.worker = ImportWorker(self.db_file, Path(path))
        self.worker.folder_started.connect(self._on_folder)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self._total = -1
        self.progress.setRange(0, 0)           # indéterminé tant que le total n'est pas connu
        self.progress.show()
        self.cancel_btn.show()
        self.worker.start()

    def _on_folder(self, folder: str, total: int) -> None:
        self._total = total
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(0)
        else:
            self.progress.setRange(0, 0)
        self.statusBar().showMessage(self.tr("Import : ") + folder)

    def _on_progress(self, folder: str, done: int, errors: int) -> None:
        if self._total > 0:
            self.progress.setValue(min(done, self._total))
        self.statusBar().showMessage(self.tr("Import : {f} — {d} traités, {e} erreur(s)").format(f=folder, d=done, e=errors))

    def _end_import(self) -> None:
        self.progress.hide()
        self.cancel_btn.hide()
        self.refresh()

    def _on_done(self, rep) -> None:
        self._end_import()
        msg = (f"Moteur : {rep.engine}\nImportés : {rep.imported}\nDéjà présents : {rep.skipped_existing}\n"
               f"Éléments non-courriel ignorés : {rep.skipped_non_mail}\n"
               f"Messages vides (métadonnées seules) ignorés : {rep.skipped_empty}\nErreurs : {rep.errors}")
        if rep.cancelled:
            msg = "Import annulé (reprise possible en ré-ajoutant l'archive).\n" + msg
        if rep.error_samples:
            msg += "\n\n" + "\n".join(rep.error_samples[:5])
        dialogs.information(self, self.tr("Import terminé"), msg)

    def _on_failed(self, text: str) -> None:
        self._end_import()
        log.error("Import échoué : %s", text)
        dialogs.critical(self, self.tr("Import impossible"), text)

    # ----- export -----
    def _build_export_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.tr("Messages en fichiers EML (dossier)…"), lambda: self.start_export("eml"))
        menu.addAction(self.tr("Messages en un fichier MBOX…"), lambda: self.start_export("mbox"))
        menu.addAction(self.tr("Pièces jointes (dossier)…"), lambda: self.start_export("attachments"))
        menu.addSeparator()
        menu.addAction(self.tr("Résultats de la recherche en CSV…"), lambda: self.start_export("csv"))
        return menu

    def _table_menu(self, pos) -> None:
        menu = self._build_export_menu()
        menu.setTitle("Exporter")
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.rows[r].id for r in rows]

    def start_export(self, kind: str) -> None:
        if getattr(self, "exporter", None) and self.exporter.isRunning():
            dialogs.information(self, self.windowTitle(), self.tr("Un export est déjà en cours."))
            return
        ids = self._selected_ids() if kind != "csv" else []
        scope = (self.tr("{n} message(s) sélectionné(s)").format(n=len(ids)) if ids
                 else self.tr("tous les résultats de la vue courante"))
        if kind == "eml" or kind == "attachments":
            dest = QFileDialog.getExistingDirectory(self, self.tr("Dossier de destination — ") + scope)
        elif kind == "mbox":
            dest, _ = QFileDialog.getSaveFileName(self, self.tr("Fichier MBOX — ") + scope, "export.mbox", "MBOX (*.mbox)")
        else:
            dest, _ = QFileDialog.getSaveFileName(self, self.tr("Fichier CSV"), "resultats.csv", "CSV (*.csv)")
        if not dest:
            return
        if not ids and kind != "csv" and dialogs.question(self, self.windowTitle(), self.tr(
                "Aucun message sélectionné : exporter TOUS les résultats de la vue courante ?")) != QMessageBox.Yes:
            return
        self.exporter = ExportWorker(self.db_file, kind, Path(dest), ids=ids or None, query=self.search_box.text(),
                                     filters=self._filters(), sort=self.model.sort_key, descending=self.model.descending)
        self.exporter.progress.connect(self._export_progress)
        self.exporter.finished_ok.connect(self._export_done)
        self.exporter.failed.connect(self._export_failed)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_btn.setText(self.tr("Annuler l'export"))
        self.cancel_btn.show()
        self.statusBar().showMessage(self.tr("Export en cours…"))
        self.exporter.start()

    def _cancel_current(self) -> None:
        for w in (getattr(self, 'exporter', None), self.worker):
            if w is not None and w.isRunning():
                w.cancel()
                return

    def _export_progress(self, done: int, total: int) -> None:
        if total > 0 and done != total or total == done and total > 0:
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(done)
        self.statusBar().showMessage(self.tr("Export : {d}/{t}").format(d=done, t=total))

    def _end_export(self) -> None:
        self.progress.hide()
        self.cancel_btn.hide()
        self.cancel_btn.setText(self.tr("Annuler l'import"))

    def _export_done(self, rep) -> None:
        self._end_export()
        msg = f"Écrits : {rep.written}\nIgnorés (erreur) : {rep.skipped}\nDestination : {rep.target}"
        if rep.cancelled:
            msg = "Export annulé.\n" + msg
        if rep.errors:
            msg += f"\n\n{len(rep.errors)} avertissement(s) :\n" + "\n".join(rep.errors[:8])
        dialogs.information(self, self.tr("Export terminé"), msg)

    def _export_failed(self, text: str) -> None:
        self._end_export()
        dialogs.critical(self, self.tr("Export impossible"), text)

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, ArchiveTree.ROLE)[2] is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(self.tr("Décharger cette archive de l'index"), self.remove_archive)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def remove_archive(self) -> None:
        aid = self.tree.selected_archive()
        if aid is None:
            dialogs.information(self, self.windowTitle(), self.tr("Sélectionnez une archive (ou un de ses dossiers) dans l'arbre."))
            return
        if self.worker and self.worker.isRunning():
            dialogs.information(self, self.windowTitle(), self.tr("Un import est en cours : attendez la fin ou annulez-le."))
            return
        row = self.conn.execute("SELECT path, (SELECT count(*) FROM messages WHERE archive_id=a.id) n FROM archives a WHERE id=?", (aid,)).fetchone()
        if not row:
            return
        name = Path(row["path"]).name
        if dialogs.question(self, self.windowTitle(), self.tr(
                "Décharger « {n} » ({c} messages) de l'index ?\n\nLe fichier source n'est pas modifié ; "
                "vous pourrez le recharger plus tard.").format(n=name, c=row["n"])) != QMessageBox.Yes:
            return
        self.readers.evict(row["path"])
        self.remover = RemoveWorker(self.db_file, aid)
        self.remover.done.connect(self._unloaded)
        self.remover.failed.connect(lambda t: (self._unloaded(), dialogs.critical(self, self.windowTitle(), t)))
        self.progress.setRange(0, 0)
        self.progress.show()
        self.statusBar().showMessage(self.tr("Déchargement de « {n} »…").format(n=name))
        self.rm.setEnabled(False)
        self.remover.start()

    def _unloaded(self) -> None:
        self.progress.hide()
        self.viewer.clear()
        self.refresh()
        self.statusBar().showMessage(self.tr("Archive déchargée."), 6000)

    def backup_db(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(self, self.tr("Sauvegarder la base"), "archive-backup.db", "SQLite (*.db)")
        if dest:
            src = connect(self.db_file)
            try:
                backup(src, dest)
            finally:
                src.close()
            self.statusBar().showMessage(self.tr("Base sauvegardée : ") + dest, 6000)

    # ----- pièces jointes -----
    def save_attachment(self, mid: int, idx: int, filename: str) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Enregistrer la pièce jointe dans…"))
        if not folder:
            return
        arch = self.conn.execute(
            "SELECT a.kind, a.path, a.engine, m.source_ref FROM messages m JOIN archives a ON a.id=m.archive_id WHERE m.id=?",
            (mid,)).fetchone()
        try:
            r = self.readers.get(arch["kind"], arch["path"], arch["engine"])
            target, digest = extract_stream(r.open_attachment(arch["source_ref"], idx), Path(folder), filename)
            w = connect(self.db_file)
            try:
                w.execute("UPDATE attachments SET sha256=? WHERE message_id=? AND idx=?", (digest, mid, idx))
            finally:
                w.close()
            self.statusBar().showMessage(self.tr("Enregistré : ") + str(target), 8000)
        except Exception as exc:  # noqa: BLE001
            log.exception("Extraction de pièce jointe")
            dialogs.warning(self, self.tr("Extraction impossible"), f"{type(exc).__name__}: {exc}")
