"""Import en tâche de fond : l'UI ne gèle jamais.

Choix MVP : QThread avec sa propre connexion SQLite (WAL). Un crash natif de libpff
tuerait aussi l'UI ; l'isolation en processus séparé reste à faire (voir « Limites connues » du README)."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.database import open_database
from ..services.import_service import ImportReport, ProgressSink, import_archive


class _Sink(ProgressSink):
    def __init__(self, worker):
        self.w = worker

    def on_folder(self, path, total):
        self.w.folder_started.emit("/".join(path), -1 if total is None else total)

    def on_progress(self, folder, done, errors):
        self.w.progress.emit("/".join(folder), done, errors)


class ImportWorker(QThread):
    folder_started = Signal(str, int)      # dossier, total (-1 = inconnu)
    progress = Signal(str, int, int)       # dossier, traités, erreurs
    finished_ok = Signal(object)           # ImportReport
    failed = Signal(str)

    def __init__(self, db_file: Path, archive: Path, engine: str | None = None):
        super().__init__()
        self.db_file, self.archive, self.engine = db_file, archive, engine
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            conn = open_database(self.db_file, bulk=True)
            try:
                rep: ImportReport = import_archive(conn, self.archive, engine=self.engine,
                                                   progress=_Sink(self), cancel=self.cancel_event)
            finally:
                conn.close()
            self.finished_ok.emit(rep)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
