from __future__ import annotations

import sys

from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .config.settings import db_path, setup_logging


def main() -> int:
    if "--selftest" in sys.argv:
        from .selftest import run
        return run()
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Mail Archive Explorer")
    from .ui.main_window import MainWindow
    win = MainWindow(db_path())
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
