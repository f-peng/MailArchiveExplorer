"""Visualiseur : en-têtes, corps (HTML sécurisé ou texte), pièces jointes."""
from __future__ import annotations

import base64
import html as htmllib
import re
import sqlite3
import zlib

from .dialogs import messages as dialogs
from .html_sanitizer import MAX_HTML_BYTES, sanitize_html
from .message_list import short_name, split_recipients
from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QScrollArea, QFrame, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEBENGINE = True
except ImportError:  # repli texte brut (SPEC §6)
    HAVE_WEBENGINE = False

MAX_INLINE = 5_000_000
_CID = re.compile(r'cid:([^"\'\s>)]+)', re.IGNORECASE)


def inline_cids(html: str, images: dict[str, tuple[str, bytes]]) -> str:
    """Remplace cid:xxx par une URI data: tirée des pièces jointes du message."""
    def repl(m):
        key = m.group(1).strip("<>")
        if key in images:
            mime, data = images[key]
            return f"data:{mime or 'application/octet-stream'};base64,{base64.b64encode(data).decode()}"
        return m.group(0)
    return _CID.sub(repl, html)


if HAVE_WEBENGINE:
    class _Blocker(QWebEngineUrlRequestInterceptor):
        """Bloque tout réseau ; seuls data: et about: passent. Les images distantes sont bloquées
        tant que `allow_remote_images` est faux (et jamais autorisées autrement que ponctuellement)."""
        allow_remote_images = False

        def interceptRequest(self, info):
            scheme = info.requestUrl().scheme()
            if scheme in ("data", "about", "blob"):
                return
            is_image = info.resourceType() == info.ResourceType.ResourceTypeImage
            if is_image and self.allow_remote_images and scheme in ("http", "https"):
                return
            info.block(True)

    class _SafePage(QWebEnginePage):
        def __init__(self, profile, parent, on_link):
            super().__init__(profile, parent)
            self.on_link = on_link

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
                self.on_link(url)
                return False
            return url.scheme() in ("data", "about")

    class SafeHtmlView(QWebEngineView):
        render_failed = Signal(str)

        def __init__(self):
            super().__init__()
            self._resetting = False
            self.loadFinished.connect(self._loaded)
            self.profile_ = QWebEngineProfile(self)          # off-the-record (sans nom = pas de persistance)
            self.blocker = _Blocker(self)
            self.profile_.setUrlRequestInterceptor(self.blocker)
            self.setPage(_SafePage(self.profile_, self, self._link))
            s = self.page().settings()
            s.setAttribute(QWebEngineSettings.JavascriptEnabled, False)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
            s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
            s.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, False)
            s.setAttribute(QWebEngineSettings.AutoLoadIconsForPage, False)
            for name in ("DnsPrefetchEnabled", "HyperlinkAuditingEnabled", "LocalStorageEnabled",
                         "NavigateOnDropEnabled", "ErrorPageEnabled", "ScreenCaptureEnabled",
                         "WebRTCPublicInterfacesOnly", "AllowGeolocationOnInsecureOrigins", "FullScreenSupportEnabled"):
                attr = getattr(QWebEngineSettings.WebAttribute, name, None)
                if attr is not None:
                    s.setAttribute(attr, False)
            self.setContextMenuPolicy(Qt.NoContextMenu)

        def shutdown(self) -> None:
            """Libère la page avant le profil (évite l'avertissement Qt à la fermeture)."""
            page = self.page()
            self.setPage(None)
            page.deleteLater()

        def _link(self, url: QUrl) -> None:
            if url.scheme() not in ("http", "https", "mailto"):
                return
            r = dialogs.question(self, "Ouvrir un lien externe",
                                 f"Ouvrir dans le navigateur système ?\n\n{url.toString()}")
            if r == QMessageBox.Yes:
                QDesktopServices.openUrl(url)

        def _loaded(self, ok: bool) -> None:
            if ok or self._resetting:
                self._resetting = False
                return
            self._resetting = True                   # évite toute boucle si about:blank échoue aussi
            self.setUrl(QUrl("about:blank"))         # ne jamais laisser le contenu d'un autre message affiché
            self.render_failed.emit("chargement HTML échoué")

        def show_html(self, html: str, remote_images: bool) -> bool:
            """Affiche le HTML assaini. Retourne False (rien n'est chargé) s'il dépasse la limite de setHtml()."""
            safe = sanitize_html(html, remote_images)
            if len(safe.encode("utf-8", "replace")) > MAX_HTML_BYTES:
                self.setUrl(QUrl("about:blank"))
                return False
            self.blocker.allow_remote_images = remote_images
            self.setHtml(safe, QUrl("about:blank"))
            return True


class MessageViewer(QWidget):
    attachment_requested = Signal(int, int, str)   # message_id, idx, filename

    def __init__(self, conn: sqlite3.Connection, readers):
        super().__init__()
        self.conn = conn
        self.readers = readers
        self.current_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.expand_rcpt = False
        self.muted = "#5b6370"

        # --- zone haute (en-tête + avis + pièces jointes) : défile et reste bornée en hauteur ---
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(8, 6, 8, 6)
        self.header = QLabel()
        self.header.setTextFormat(Qt.RichText)
        self.header.setWordWrap(True)
        self.header.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.header.linkActivated.connect(self._toggle_rcpt)
        tl.addWidget(self.header)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.hide()
        tl.addWidget(self.notice)
        self.atts = QListWidget()
        self.atts.hide()
        self.atts.itemDoubleClicked.connect(self._att_clicked)
        tl.addWidget(self.atts)
        opts = QHBoxLayout()
        self.prefer_html = QCheckBox("Affichage HTML")
        self.prefer_html.setChecked(True)
        self.prefer_html.toggled.connect(lambda _: self.show_message(self.current_id) if self.current_id else None)
        self.remote = QCheckBox("Images distantes")
        self.remote.setToolTip("Peut révéler votre lecture à l'expéditeur ; bloquées par défaut")
        self.remote.toggled.connect(lambda _: self.show_message(self.current_id) if self.current_id else None)
        opts.addWidget(self.prefer_html)
        opts.addWidget(self.remote)
        opts.addStretch(1)
        tl.addLayout(opts)
        self.top_scroll = QScrollArea()
        self.top_scroll.setWidgetResizable(True)
        self.top_scroll.setFrameShape(QFrame.NoFrame)
        self.top_scroll.setWidget(top)

        # --- corps : prioritaire, jamais écrasé ---
        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(220)
        self.text = QPlainTextEdit(readOnly=True)
        self.stack.addWidget(self.text)
        self.web = None
        if HAVE_WEBENGINE:
            self.web = SafeHtmlView()
            self.stack.addWidget(self.web)
        else:
            self.web_fallback = QTextBrowser()
            self.web_fallback.setOpenLinks(False)
            self.stack.addWidget(self.web_fallback)

        if self.web is not None:
            self.web.render_failed.connect(lambda _msg: self._html_failed(None))
        self.top = top
        lay.addWidget(self.top_scroll)
        lay.addWidget(self.stack, 1)          # le corps prend tout l'espace restant

    MAX_TOP = 260

    def _fit_top(self) -> None:
        """Hauteur de la zone haute = son contenu, plafonnée (au-delà elle défile)."""
        w = max(self.width() - 24, 300)
        h = self.top.layout().totalHeightForWidth(w)
        self.top_scroll.setFixedHeight(min(max(h, 40) + 6, self.MAX_TOP))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_top()

    def _toggle_rcpt(self, _link: str) -> None:
        self.expand_rcpt = not self.expand_rcpt
        if self.current_id:
            self.show_message(self.current_id)

    def _rcpt_html(self, recipients: str | None) -> str:
        parts = split_recipients(recipients)
        e = htmllib.escape
        if len(parts) <= 4:
            return e(", ".join(parts))
        if self.expand_rcpt:
            return e(", ".join(parts)) + " <a href='r'>réduire</a>"
        return e(", ".join(short_name(p) for p in parts[:4])) + f" <a href='r'>+{len(parts) - 4} autres : tout afficher</a>"

    def apply_colors(self, c: dict) -> None:
        self.muted = c["muted"]
        self.notice.setStyleSheet(f"background:{c['notice_bg']}; color:{c['notice_fg']}; padding:6px 10px; border-radius:6px;")
        if self.current_id:
            self.show_message(self.current_id)

    def shutdown(self) -> None:
        if self.web is not None:
            self.web.shutdown()

    def clear(self) -> None:
        self.atts.hide()
        self.current_id = None
        self.header.setText("")
        self.notice.hide()
        self.text.setPlainText("")
        self.atts.clear()
        self._fit_top()

    def show_message(self, mid: int) -> None:
        if mid != self.current_id:
            self.expand_rcpt = False
            if self.remote.isChecked():          # l'autorisation ne vaut que pour le message courant
                self.remote.blockSignals(True)
                self.remote.setChecked(False)
                self.remote.blockSignals(False)
        self.current_id = mid
        m = self.conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        if not m:
            return
        b = self.conn.execute("SELECT body_html, headers FROM message_bodies WHERE message_id=?", (mid,)).fetchone()
        e = htmllib.escape
        self.header.setText(
            f"<div style='font-size:17px; font-weight:600'>{e(m['subject'] or '(sans objet)')}</div>"
            f"<table cellspacing='2'>"
            f"<tr><td style='color:{self.muted}'>De</td><td>&nbsp;{e(m['sender'] or '(inconnu)')}</td></tr>"
            f"<tr><td style='color:{self.muted}'>À</td><td>&nbsp;{self._rcpt_html(m['recipients'])}</td></tr>"
            f"<tr><td style='color:{self.muted}'>Date</td><td>&nbsp;{e((m['sent_at'] or '(absente ou invalide)'))} UTC</td></tr>"
            f"<tr><td style='color:{self.muted}'>Dossier</td><td>&nbsp;{e(self._folder_label(mid))}</td></tr></table>")
        self.atts.clear()
        rows = self.conn.execute("SELECT * FROM attachments WHERE message_id=? ORDER BY idx", (mid,)).fetchall()
        for a in rows:
            size = f"{a['size']:,}".replace(",", " ") + " o" if a["size"] is not None else "?"
            it = QListWidgetItem(f"📎 {a['filename'] or '(sans nom)'}  [{a['mime'] or 'type inconnu'}, {size}]  — double-clic : enregistrer")
            it.setData(Qt.UserRole, (a["idx"], a["filename"] or "piece_jointe"))
            self.atts.addItem(it)
        self.atts.setVisible(bool(rows))
        self.atts.setFixedHeight(min(len(rows), 4) * 22 + 8)
        preview_only = (not (b and b["body_html"])) and len(m["body_text"] or "") <= 260 and \
            self.conn.execute("SELECT kind FROM archives WHERE id=?", (m["archive_id"],)).fetchone()["kind"] == "olm"
        self.notice.setVisible(preview_only)
        if preview_only:
            self.notice.setText("Aperçu seul : le corps complet de ce message n'est pas présent dans l'archive OLM.")
        html = zlib.decompress(b["body_html"]).decode("utf-8", "replace") if b and b["body_html"] else None
        if html and self.prefer_html.isChecked():
            images = self._inline_images(rows, mid)
            html = inline_cids(html, images)
            if self.web is not None:
                if self.web.show_html(html, self.remote.isChecked()):
                    self.stack.setCurrentWidget(self.web)
                else:
                    self._html_failed(m)
            else:
                self.web_fallback.setPlainText(re.sub(r"<[^>]+>", "", html))
                self.stack.setCurrentWidget(self.web_fallback)
        else:
            self.text.setPlainText(m["body_text"] or "(message sans corps)")
            self.stack.setCurrentWidget(self.text)
        self._fit_top()

    def _html_failed(self, m) -> None:
        """HTML trop volumineux ou illisible : texte brut + avertissement (jamais l'ancien contenu)."""
        if m is None and self.current_id:
            m = self.conn.execute("SELECT body_text FROM messages WHERE id=?", (self.current_id,)).fetchone()
        self.text.setPlainText((m["body_text"] if m else "") or "(message sans corps texte)")
        self.stack.setCurrentWidget(self.text)
        self.notice.setText("Affichage HTML impossible (message trop volumineux ou invalide) : texte brut affiché.")
        self.notice.show()
        self._fit_top()

    def _folder_label(self, mid: int) -> str:
        r = self.conn.execute("SELECT fo.path FROM messages m JOIN folders fo ON fo.id=m.folder_id WHERE m.id=?", (mid,)).fetchone()
        return (r["path"] if r else "").replace("/", " › ")

    def _inline_images(self, rows, mid) -> dict[str, tuple[str, bytes]]:
        """Charge les pièces jointes `cid` (petites) pour les images incorporées."""
        wanted = [a for a in rows if a["content_id"] and (a["size"] or 0) <= MAX_INLINE]
        if not wanted:
            return {}
        arch = self.conn.execute(
            "SELECT a.kind, a.path, a.engine, m.source_ref FROM messages m JOIN archives a ON a.id=m.archive_id WHERE m.id=?",
            (mid,)).fetchone()
        out = {}
        try:
            r = self.readers.get(arch["kind"], arch["path"], arch["engine"])
            for a in wanted:
                out[a["content_id"]] = (a["mime"] or "", r.open_attachment(arch["source_ref"], a["idx"]).read())
        except Exception:  # noqa: BLE001 - image absente : on affiche le message sans
            return out
        return out

    def _att_clicked(self, item: QListWidgetItem) -> None:
        idx, name = item.data(Qt.UserRole)
        self.attachment_requested.emit(self.current_id, idx, name)
