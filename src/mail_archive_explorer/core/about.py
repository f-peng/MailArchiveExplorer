"""Informations de version et de diagnostic (sans Qt)."""
from __future__ import annotations

import platform
import sqlite3
import sys

from .. import __version__

REPO_URL = "https://github.com/f-peng/MailArchiveExplorer"
LICENSE_NAME = "GNU GPL v3 or later"


def diagnostics() -> dict[str, str]:
    try:
        import pypff
        pff = pypff.get_version()
    except Exception:  # noqa: BLE001
        pff = "n/a"
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "pypff": pff,
        "system": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "frozen": "yes" if getattr(sys, "frozen", False) else "no",
    }
