"""Décodage bytes -> str avec codepages Windows/MAPI et repli."""
from __future__ import annotations

import codecs

from .textutil import scrub

# Pages de code Windows/MAPI sans nom Python évident.
_SPECIAL = {20127: "ascii", 65001: "utf-8", 1200: "utf-16-le", 1201: "utf-16-be", 65000: "utf-7", 28591: "latin-1"}


# Codecs Python qui ne sont pas de vrais jeux de caractères : un « charset= » malveillant ne doit pas les activer
_FORBIDDEN = {"unicode_escape", "raw_unicode_escape", "rot_13", "punycode", "idna", "undefined", "utf_8_sig_"}


def codec_for(codepage: int | str | None) -> str | None:
    if codepage is None:
        return None
    if isinstance(codepage, int):
        name = _SPECIAL.get(codepage, f"cp{codepage}")
    else:
        name = str(codepage)
    try:
        info = codecs.lookup(name)
    except (LookupError, ValueError):
        return None
    if info.name in _FORBIDDEN or not getattr(info, "_is_text_encoding", True):
        return None
    return info.name


def decode_body(data: bytes | None, *hints: int | str | None) -> str | None:
    """Décode en privilégiant UTF-8 strict (les pages de code déclarées par MAPI sont souvent
    fausses : un texte UTF-8 étiqueté latin-1 donnerait « JÃ¶rn »), puis les indices, puis cp1252."""
    return scrub(_decode(data, *hints))


def _decode(data: bytes | None, *hints: int | str | None) -> str | None:
    if data is None:
        return None
    if not data:
        return ""
    # UTF-16 : seulement si un indice l'annonce, jamais en essai à l'aveugle
    utf16 = {codec_for(h) for h in hints} & {"utf-16", "utf-16le", "utf-16be"}
    if not utf16:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            pass
    for hint in hints:
        name = codec_for(hint)
        if name:
            try:
                return data.decode(name)
            except (UnicodeDecodeError, ValueError):
                continue
    return data.decode("cp1252", errors="replace")
