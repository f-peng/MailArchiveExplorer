"""Analyse de la saisie utilisateur -> requête FTS5 sûre (échappement systématique).

Syntaxe : mots, "expressions exactes", AND / OR / NOT (majuscules), parenthèses,
préfixe de champ (from: to: subject: body: filename:, alias français), joker final `mot*`,
filtres hors FTS : before:YYYY-MM-DD after:YYYY-MM-DD has:attachment.
Tout terme est émis entre guillemets : aucune syntaxe FTS5 n'est interprétable depuis la saisie.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class QueryError(ValueError):
    """Requête invalide, message destiné à l'utilisateur."""


@dataclass
class ParsedQuery:
    fts: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    has_attachments: bool | None = None


FIELDS = {
    "from": "sender", "de": "sender", "expediteur": "sender", "expéditeur": "sender",
    "to": "recipients", "a": "recipients", "à": "recipients", "destinataire": "recipients",
    "subject": "subject", "objet": "subject", "sujet": "subject",
    "body": "body_text", "corps": "body_text",
    "filename": "attachment_names", "pj": "attachment_names", "fichier": "attachment_names",
}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOKEN = re.compile(r'\s*(?:(\()|(\))|"([^"]*)"?|([^\s()"]+))')
_HAS_ALNUM = re.compile(r"\w", re.UNICODE)


def _quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


@dataclass
class _Tok:
    kind: str  # LP RP TERM PHRASE OP
    value: str = ""


def _lex(text: str) -> list[_Tok]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        lp, rp, phrase, word = m.groups()
        if lp:
            out.append(_Tok("LP"))
        elif rp:
            out.append(_Tok("RP"))
        elif phrase is not None:
            out.append(_Tok("PHRASE", phrase))
        elif word is not None:
            out.append(_Tok("OP", word) if word in ("AND", "OR", "NOT") else _Tok("TERM", word))
    return out


class _Parser:
    def __init__(self, toks: list[_Tok]):
        self.t, self.i = toks, 0

    def peek(self) -> _Tok | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def parse(self) -> str | None:
        if not self.t:
            return None
        node = self.or_expr()
        if self.peek() is not None:
            raise QueryError("Parenthèse fermante inattendue.")
        return node

    def or_expr(self) -> str:
        parts = [self.and_expr()]
        while (p := self.peek()) and p.kind == "OP" and p.value == "OR":
            self.i += 1
            parts.append(self.and_expr())
        return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"

    def and_expr(self) -> str:
        pos: list[str] = []
        neg: list[str] = []
        negate = False
        while True:
            p = self.peek()
            if p is None or p.kind == "RP" or (p.kind == "OP" and p.value == "OR"):
                break
            if p.kind == "OP" and p.value == "AND":
                self.i += 1
                continue
            if p.kind == "OP" and p.value == "NOT":
                if negate:
                    raise QueryError("Deux NOT consécutifs ne sont pas autorisés.")
                self.i += 1
                negate = True
                continue
            atom = self.atom()
            if atom is None:
                negate = False
                continue
            (neg if negate else pos).append(atom)
            negate = False
        if negate:
            raise QueryError("NOT doit être suivi d'un terme.")
        if not pos:
            if neg:
                raise QueryError("Une requête ne peut pas contenir uniquement des exclusions (NOT).")
            raise QueryError("Expression vide.")
        out = pos[0] if len(pos) == 1 else "(" + " AND ".join(pos) + ")"
        if neg:
            out = f"({out} NOT " + (neg[0] if len(neg) == 1 else "(" + " OR ".join(neg) + ")") + ")"
        return out

    def atom(self, column: str | None = None) -> str | None:
        p = self.peek()
        if p is None:
            raise QueryError("Expression incomplète.")
        if p.kind == "LP":
            self.i += 1
            if self.peek() is None:
                raise QueryError("Parenthèse fermante manquante.")
            inner = self.or_expr()
            if not (self.peek() and self.peek().kind == "RP"):
                raise QueryError("Parenthèse fermante manquante.")
            self.i += 1
            return inner if column is None else self._scope(column, inner)
        if p.kind == "PHRASE":
            self.i += 1
            return self._term(p.value, column, wildcard=False)
        if p.kind == "TERM":
            self.i += 1
            word = p.value
            if column is None and ":" in word:
                field_name, _, rest = word.partition(":")
                key = field_name.lower()
                if key in FIELDS:
                    col = FIELDS[key]
                    if rest:
                        return self._term(rest, col, wildcard=True)
                    nxt = self.peek()
                    if nxt is None or nxt.kind not in ("TERM", "PHRASE", "LP"):
                        raise QueryError(f"« {field_name}: » doit être suivi d'un terme.")
                    return self.atom(col)
            return self._term(word, column, wildcard=True)
        raise QueryError("Opérateur inattendu : " + (p.value or p.kind))

    @staticmethod
    def _scope(column: str, inner: str) -> str:
        return f"{column} : {inner}"

    @staticmethod
    def _term(text: str, column: str | None, wildcard: bool) -> str | None:
        star = wildcard and text.endswith("*")
        text = text.rstrip("*") if star else text
        if not _HAS_ALNUM.search(text):
            return None  # ponctuation seule : ignorée
        q = _quote(text) + ("*" if star else "")
        return f"{column} : {q}" if column else q


MAX_QUERY_CHARS = 1000
MAX_TERMS = 100
MAX_DEPTH = 30


def parse_query(text: str) -> ParsedQuery:
    """Retourne la requête FTS5 et les filtres extraits. Lève QueryError (message clair) si invalide."""
    text = (text or "").replace("\x00", " ")
    if len(text) > MAX_QUERY_CHARS:
        raise QueryError(f"Requête trop longue (maximum {MAX_QUERY_CHARS} caractères).")
    if text.count("(") > MAX_DEPTH:
        raise QueryError("Trop de parenthèses imbriquées.")
    try:
        return _parse(text)
    except RecursionError:
        raise QueryError("Requête trop complexe.") from None


def _parse(text: str) -> ParsedQuery:
    result = ParsedQuery()
    remaining = []
    for tok in text.split():
        low = tok.lower()
        if low.startswith(("before:", "avant:", "after:", "apres:", "après:")):
            key, _, val = tok.partition(":")
            if not _DATE.match(val):
                raise QueryError(f"Date invalide pour « {key}: » (format AAAA-MM-JJ attendu).")
            if key.lower() in ("before", "avant"):
                result.date_to = val
            else:
                result.date_from = val
        elif low in ("has:attachment", "has:pj", "a:pj", "avec:pj"):
            result.has_attachments = True
        else:
            remaining.append(tok)
    # reconstruit en conservant les guillemets : on re-split proprement sur le texte d'origine
    cleaned = _strip_filters(text)
    toks = _lex(cleaned)
    if sum(1 for t in toks if t.kind in ("TERM", "PHRASE")) > MAX_TERMS:
        raise QueryError(f"Requête trop complexe (maximum {MAX_TERMS} termes).")
    result.fts = _Parser(toks).parse() if cleaned.strip() else None
    return result


def _strip_filters(text: str) -> str:
    pat = re.compile(r'(?<![\w"])(?:before|avant|after|apres|après):\S*|(?<![\w"])(?:has:attachment|has:pj|a:pj|avec:pj)(?=\s|$)', re.IGNORECASE)
    return pat.sub(" ", text)
