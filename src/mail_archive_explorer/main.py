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
    from PySide6.QtCore import QLocale, QSettings
    from .core.i18n import resolve, set_language
    set_language(resolve(QSettings("MailArchiveExplorer", "ui").value("language", "auto"), QLocale.system().name()))
    from .ui.main_window import MainWindow
    win = MainWindow(db_path())
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
