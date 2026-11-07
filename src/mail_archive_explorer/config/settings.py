"""Emplacements des données et journalisation."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("MAE_DATA_DIR")
    if env:
        base = Path(env)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MailArchiveExplorer"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / "MailArchiveExplorer"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "MailArchiveExplorer"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "archive.db"


def setup_logging() -> None:
    logs = data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
