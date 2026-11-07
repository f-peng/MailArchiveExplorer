"""Point d'entrée PyInstaller."""
import multiprocessing
import sys

from mail_archive_explorer.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
