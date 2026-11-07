"""Nettoyage de texte issu d'archives non fiables."""
from __future__ import annotations

import re

_SURROGATES = re.compile("[\ud800-\udfff]")


def scrub(value):
    """Remplace les substituts UTF-16 isolés (non encodables en UTF-8, donc rejetés par SQLite) et
    les NUL par U+FFFD / rien. Accepte None."""
    if value is None or not isinstance(value, str):
        return value
    value = value.replace("\x00", "")
    return _SURROGATES.sub("\ufffd", value)
