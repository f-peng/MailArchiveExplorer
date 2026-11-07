"""Arbre archives / dossiers avec compteurs."""
from __future__ import annotations

import os
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class ArchiveTree(QTreeWidget):
    ROLE = Qt.UserRole

    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn
        self.setHeaderLabels(["Archives et dossiers"])

    def selected_archive(self) -> int | None:
        item = self.currentItem()
        return item.data(0, self.ROLE)[2] if item else None

    def reload(self) -> None:
        self.clear()
        total = self.conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        root = QTreeWidgetItem([f"Tous les messages ({total})"])
        root.setData(0, self.ROLE, ("all", None, None))
        self.addTopLevelItem(root)
        counts = {r["folder_id"]: r["n"] for r in self.conn.execute(
            "SELECT folder_id, count(*) n FROM messages GROUP BY folder_id")}
        for a in self.conn.execute("SELECT id, path FROM archives ORDER BY id"):
            n_a = self.conn.execute("SELECT count(*) FROM messages WHERE archive_id=?", (a["id"],)).fetchone()[0]
            it = QTreeWidgetItem([f"{os.path.basename(a['path'])} ({n_a})"])
            it.setToolTip(0, a["path"])
            it.setData(0, self.ROLE, ("archive", a["id"], a["id"]))
            root.addChild(it)
            nodes: dict[tuple[str, ...], QTreeWidgetItem] = {}
            for f in self.conn.execute("SELECT id, path FROM folders WHERE archive_id=? ORDER BY path", (a["id"],)):
                parts = tuple(f["path"].split("/"))
                parent = it
                for depth in range(1, len(parts)):      # crée les niveaux intermédiaires
                    key = parts[:depth]
                    if key not in nodes:
                        node = QTreeWidgetItem([parts[depth - 1]])
                        node.setData(0, self.ROLE, ("none", None, a["id"]))
                        parent.addChild(node)
                        nodes[key] = node
                    parent = nodes[key]
                leaf = nodes.get(parts)
                label = f"{parts[-1]} ({counts.get(f['id'], 0)})"
                if leaf is None:
                    leaf = QTreeWidgetItem([label])
                    parent.addChild(leaf)
                    nodes[parts] = leaf
                else:
                    leaf.setText(0, label)
                leaf.setData(0, self.ROLE, ("folder", f["id"], a["id"]))
        self.expandToDepth(1)
