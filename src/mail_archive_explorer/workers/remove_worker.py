"""Déchargement d'une archive de l'index en tâche de fond (la suppression cascade peut être longue)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.archive_manager import remove_archive
from ..core.database import open_database


class RemoveWorker(QThread):
    done = Signal()
    failed = Signal(str)

    def __init__(self, db_file: Path, archive_id: int):
        super().__init__()
        self.db_file, self.archive_id = db_file, archive_id

    def run(self) -> None:
        try:
            conn = open_database(self.db_file, bulk=True)
            try:
                remove_archive(conn, self.archive_id)
            finally:
                conn.close()
            self.done.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
