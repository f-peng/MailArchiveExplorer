"""Assainissement du HTML des messages avant affichage (défense en profondeur).

Pourquoi : l'intercepteur de requêtes de WebEngine ne voit pas toutes les connexions réseau.
Un audit a montré que `<link rel="preconnect" href="http://hôte">` ouvre une connexion TCP même
quand les images distantes sont bloquées. On retire donc les éléments qui déclenchent du réseau
ou modifient la page (link, base, meta, script, iframe, object, embed...), puis on impose une
politique CSP stricte. Sans dépendance Qt : testable seule."""
from __future__ import annotations

import re
from html.parser import HTMLParser

# Éléments supprimés AVEC leur contenu
_DROP_WITH_CONTENT = {"script", "iframe", "object", "applet", "frameset", "noscript"}
# Éléments sans contenu utile supprimés (balises seules)
_DROP_TAG = {"link", "base", "meta", "embed", "frame", "param", "source", "track"}

# Filet de sécurité si l'analyseur et Chromium divergent : toute occurrence résiduelle est neutralisée
_RESIDUAL = re.compile(r"<[\s/]*(link|base|meta)\b", re.IGNORECASE)

MAX_HTML_BYTES = 1_900_000     # setHtml() échoue silencieusement au-delà de ~2 Mo


def csp(allow_remote_images: bool) -> str:
    img = "img-src data: http: https:" if allow_remote_images else "img-src data:"
    return (f"default-src 'none'; {img}; style-src 'unsafe-inline'; font-src data:; "
            "form-action 'none'; base-uri 'none'; frame-src 'none'; object-src 'none'; media-src 'none'")


class _Rebuilder(HTMLParser):
    def __init__(self, csp_value: str):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.skip_depth = 0
        self.skip_tag = ""
        self.csp_meta = f'<meta http-equiv="Content-Security-Policy" content="{csp_value}">'
        self.marker = "\x00CSP\x00"           # remplacé APRÈS le filet de sécurité, pour ne pas le détruire
        self.csp_done = False

    def _csp(self) -> None:
        if not self.csp_done:
            self.out.append(self.marker)
            self.csp_done = True

    def handle_decl(self, decl):          # <!DOCTYPE ...> : avant le CSP pour ne pas passer en mode quirks
        if not self.skip_depth:
            self.out.append(f"<!{decl}>")

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in _DROP_WITH_CONTENT:
            self.skip_tag, self.skip_depth = tag, 1
            return
        if tag in _DROP_TAG:
            return
        self._csp()
        self.out.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if self.skip_depth or tag in _DROP_TAG or tag in _DROP_WITH_CONTENT:
            return
        self._csp()
        self.out.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
            return
        if tag in _DROP_TAG:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip_depth:
            if data.strip():
                self._csp()
            self.out.append(data)

    def handle_entityref(self, name):
        if not self.skip_depth:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip_depth:
            self.out.append(f"&#{name};")

    def handle_comment(self, data):       # commentaires supprimés (conditionnels Outlook inclus)
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass


def sanitize_html(html: str, allow_remote_images: bool = False) -> str:
    """HTML sans éléments réseau/actifs, précédé d'une politique CSP stricte."""
    html = html.replace("\x00", "")
    p = _Rebuilder(csp(allow_remote_images))
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - HTML malformé au point de lever : on affiche le texte seul
        body = re.sub(r"<[^>]*>", "", html)
        return f"<html><head>{p.csp_meta}</head><body><pre>{_escape(body)}</pre></body></html>"
    p._csp()                                # document sans contenu : CSP quand même
    out = _RESIDUAL.sub("&lt;removed ", "".join(p.out))
    return out.replace(p.marker, p.csp_meta, 1)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
