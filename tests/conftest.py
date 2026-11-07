import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

PRIVATE = ROOT / "tests" / "fixtures" / "private"


def pst_file(name):
    p = PRIVATE / name
    if not p.exists():
        pytest.skip(f"PST de test absent : {p} (voir docs/PST_FEASIBILITY.md pour les sources)")
    return p


@pytest.fixture
def db(tmp_path):
    from mail_archive_explorer.core.database import open_database
    conn = open_database(tmp_path / "t.db", bulk=True)
    yield conn
    conn.close()
