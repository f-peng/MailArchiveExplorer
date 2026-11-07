"""Migrations : MIGRATIONS[n] fait passer user_version de n-1 à n."""
from __future__ import annotations

MIGRATIONS: dict[int, str] = {
    1: """
CREATE TABLE archives (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    fingerprint TEXT NOT NULL,
    engine TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(path, size, mtime)
);
CREATE TABLE folders (
    id INTEGER PRIMARY KEY,
    archive_id INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    UNIQUE(archive_id, path)
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    archive_id INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    source_ref TEXT NOT NULL,
    message_id TEXT,
    content_hash TEXT NOT NULL,
    subject TEXT,
    sender TEXT,
    recipients TEXT,
    sent_at TEXT,
    date_valid INTEGER NOT NULL DEFAULT 1,
    body_text TEXT,
    excerpt TEXT,
    has_attachments INTEGER NOT NULL DEFAULT 0,
    attachment_names TEXT,
    message_class TEXT,
    UNIQUE(archive_id, source_ref)
);
CREATE INDEX idx_msg_date ON messages(sent_at, id);
CREATE INDEX idx_msg_folder ON messages(folder_id, sent_at, id);
CREATE INDEX idx_msg_archive ON messages(archive_id);
CREATE INDEX idx_msg_mid ON messages(message_id);
CREATE INDEX idx_msg_hash ON messages(content_hash);
CREATE TABLE message_bodies (
    message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    body_html BLOB,
    headers BLOB
);
CREATE TABLE attachments (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    filename TEXT,
    mime TEXT,
    size INTEGER,
    content_id TEXT,
    is_inline INTEGER NOT NULL DEFAULT 0,
    attach_method INTEGER,
    sha256 TEXT,
    UNIQUE(message_id, idx)
);
CREATE TABLE message_sources (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    archive_id INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    folder_path TEXT NOT NULL,
    PRIMARY KEY(message_id, archive_id, folder_path)
);
CREATE TABLE import_checkpoints (
    archive_id INTEGER NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
    folder_path TEXT NOT NULL,
    last_ref TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(archive_id, folder_path)
);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    subject, sender, recipients, body_text, attachment_names,
    content='messages', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, sender, recipients, body_text, attachment_names)
    VALUES (new.id, new.subject, new.sender, new.recipients, new.body_text, new.attachment_names);
END;
CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, recipients, body_text, attachment_names)
    VALUES ('delete', old.id, old.subject, old.sender, old.recipients, old.body_text, old.attachment_names);
END;
CREATE TRIGGER messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, recipients, body_text, attachment_names)
    VALUES ('delete', old.id, old.subject, old.sender, old.recipients, old.body_text, old.attachment_names);
    INSERT INTO messages_fts(rowid, subject, sender, recipients, body_text, attachment_names)
    VALUES (new.id, new.subject, new.sender, new.recipients, new.body_text, new.attachment_names);
END;
""",
    2: """
ALTER TABLE messages ADD COLUMN to_addrs TEXT;
ALTER TABLE messages ADD COLUMN cc_addrs TEXT;
ALTER TABLE messages ADD COLUMN bcc_addrs TEXT;
""",
}
