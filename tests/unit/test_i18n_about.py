import ast
import pathlib
import re

import pytest

from mail_archive_explorer import __version__
from mail_archive_explorer.core import i18n
from mail_archive_explorer.core.about import diagnostics
from mail_archive_explorer.core.translations_en import EN
from mail_archive_explorer.ui.message_list import COLUMNS

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "mail_archive_explorer"


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    i18n.set_language("fr")


def _literals():
    found = {}
    for p in SRC.rglob("*.py"):
        if p.name in ("i18n.py", "translations_en.py"):
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    found.setdefault(a.value, p.name)
    return found


def test_toute_chaine_tr_a_une_traduction_anglaise():
    missing = [f"{f}: {k!r}" for k, f in _literals().items() if k not in EN]
    assert not missing, missing
    assert all(t[0] in EN for t in COLUMNS)                        # titres de colonnes (appel non littéral)


def test_traductions_coherentes():
    """Mêmes champs {x} des deux côtés ; aucune traduction vide ; pas de clé morte."""
    field = re.compile(r"\{(\w*)\}")
    for fr, en in EN.items():
        assert en.strip(), fr
        assert sorted(field.findall(fr)) == sorted(field.findall(en)), (fr, en)
    used = set(_literals()) | {t[0] for t in COLUMNS}
    dead = [k for k in EN if k not in used]
    assert not dead, dead


def test_tr_bascule_selon_la_langue():
    assert i18n.tr("Fermer") == "Fermer"
    i18n.set_language("en")
    assert i18n.tr("Fermer") == "Close"
    assert i18n.tr("chaîne inconnue") == "chaîne inconnue"          # repli : jamais d'exception
    i18n.set_language("zz")
    assert i18n.language() == "fr"


@pytest.mark.parametrize("pref,locale,expected", [
    ("fr", "en_US", "fr"), ("en", "fr_FR", "en"), ("auto", "fr_FR", "fr"), (None, "fr_CA", "fr"),
    ("auto", "en_GB", "en"), ("auto", "de_DE", "en"), ("zz", "fr_FR", "fr"), (None, None, "en"),
])
def test_resolution_de_la_langue(pref, locale, expected):
    assert i18n.resolve(pref, locale) == expected


def test_messages_de_requete_traduits():
    from mail_archive_explorer.core.query_parser import QueryError, parse_query
    with pytest.raises(QueryError) as fr:
        parse_query("(")
    i18n.set_language("en")
    with pytest.raises(QueryError) as en:
        parse_query("(")
    assert "parenthèse" in str(fr.value).lower() and "parenthesis" in str(en.value).lower()


def test_version_source_unique():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", __version__)
    d = diagnostics()
    assert d["version"] == __version__ and d["sqlite"] and d["python"]
    toml = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in toml and "mail_archive_explorer.__version__" in toml


def test_a_propos_texte_des_details():
    pytest.importorskip("PySide6")
    from mail_archive_explorer.ui.dialogs.about import details_text
    t = details_text(None)
    assert __version__ in t and "PySide6" in t and "SQLite" in t
