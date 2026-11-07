"""Conversion RTF -> texte brut (approximation volontairement simple)."""
from __future__ import annotations

import re

_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|([^\\{}]+)")
_SKIP_DEST = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer",
              "generator", "themedata", "colorschememapping", "latentstyles", "datastore"}


def rtf_to_text(data: bytes | str, codepage: str = "cp1252") -> str:
    s = data.decode("latin-1") if isinstance(data, bytes) else data
    out: list[str] = []
    stack: list[bool] = []
    skip = False
    ignorable_next = False
    uc = 1
    skip_chars = 0
    for m in _TOKEN.finditer(s):
        word, num, hexv, sym, brace, text = m.groups()
        if brace == "{":
            stack.append(skip)
            ignorable_next = False
        elif brace == "}":
            skip = stack.pop() if stack else False
        elif word is not None:
            if ignorable_next:
                skip = True
            ignorable_next = False
            if word in _SKIP_DEST:
                skip = True
            elif word == "uc" and num:
                uc = int(num)
            elif skip:
                continue
            elif word in ("par", "line"):
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            elif word == "u" and num:
                n = int(num)
                c = n % 65536
                out.append(chr(c) if not 0xD800 <= c <= 0xDFFF else "\ufffd")
                skip_chars = uc
        elif hexv is not None:
            if not skip:
                out.append(bytes([int(hexv, 16)]).decode(codepage, errors="replace"))
        elif sym is not None:
            if sym == "*":
                ignorable_next = True
            elif not skip and sym in "{}\\":
                out.append(sym)
        elif text is not None and not skip:
            t = text.replace("\r", "").replace("\n", "")
            if skip_chars:
                n = min(skip_chars, len(t))
                t, skip_chars = t[n:], skip_chars - n
            out.append(t)
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()
