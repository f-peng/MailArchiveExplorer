"""Export en tâche de fond (connexion lecture seule et cache de lecteurs propres au thread)."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.archive_manager import ReaderCache
from ..core.database import connect
from ..core.search import Filters
from ..services import export_service as ex


class ExportWorker(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(object)        # ExportReport
    failed = Signal(str)

    def __init__(self, db_file: Path, kind: str, dest: Path, *, ids: list[int] | None = None,
                 query: str = "", filters: Filters | None = None, sort: str = "date", descending: bool = True):
        super().__init__()
        self.db_file, self.kind, self.dest = db_file, kind, Path(dest)
        self.ids, self.query, self.filters = ids, query, filters or Filters()
        self.sort, self.descending = sort, descending
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        conn = connect(self.db_file, readonly=True)
        readers = ReaderCache()
        try:
            cb = self.progress.emit
            if self.kind == "csv":
                rep = ex.export_csv(conn, self.query, self.filters, self.dest, self.sort, self.descending,
                                    progress=cb, cancel=self.cancel_event)
            else:
                ids = self.ids if self.ids is not None else ex.collect_ids(
                    conn, self.query, self.filters, self.sort, self.descending)
                fn = {"eml": ex.export_eml, "mbox": ex.export_mbox, "attachments": ex.export_attachments}[self.kind]
                rep = fn(conn, ids, self.dest, readers, progress=cb, cancel=self.cancel_event)
            self.finished_ok.emit(rep)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            readers.close_all()
            conn.close()
