# Mail Archive Explorer

[🇫🇷 Français](README.md) · 🇬🇧 English

A **100% local** desktop application to browse, index and search mail archives: **PST/OST, OLM (Outlook for Mac), MBOX and EML**.

- No data leaves your machine; source archives are opened **read-only** and are never modified.
- Background import (cancellable and resumable), full-text search (accent-insensitive), column sorting, light and dark themes.
- Export to EML, MBOX, CSV and attachments.
- **French and English** interface (🌐 *Language* button, applied on restart; automatic by default from the system language). **About** shows the version and copyable details for bug reports.

> **Status: pre-release (`v0.1.1-rc3`).** Usable, but young: see "Known limitations".

Technical notes: [PST feasibility spike](docs/PST_FEASIBILITY.md) · [architecture](docs/ARCHITECTURE.md) (both in French).

## Installation

### Standalone executables (no Python needed)

Download the file for your system from the [Releases](https://github.com/f-peng/MailArchiveExplorer/releases) page:

| System | File |
|---|---|
| macOS (Apple Silicon) | `MailArchiveExplorer-macos-arm64.dmg` |
| Windows (x64) | `MailArchiveExplorer-windows-x64.zip` (extract it) |
| Linux (x64) | `MailArchiveExplorer-linux-x64.tar.gz` (extract it, run `MailArchiveExplorer/MailArchiveExplorer`) — *being validated* |

On Linux, install the Qt/Chromium system libraries if needed (Debian/Ubuntu: `libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libnss3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxcursor1 libxi6 libfontconfig1 libasound2`).

The executables are **not code-signed**: Windows (SmartScreen) and macOS (Gatekeeper) ask for confirmation on first launch.
- macOS: right-click the app, then *Open*, or `xattr -dr com.apple.quarantine MailArchiveExplorer.app`.
- Windows: *More info*, then *Run anyway*.

Size: about 500 MB unpacked (Qt WebEngine). Every published file carries a build provenance attestation: `gh attestation verify <file> --repo f-peng/MailArchiveExplorer`.

### From source

Python 3.12 or later (developed on 3.14).

```bash
git clone https://github.com/f-peng/MailArchiveExplorer.git
cd MailArchiveExplorer
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m mail_archive_explorer
```

- `libpff-python` (the `pypff` module) is a binary wheel with no native dependency. It is the primary PST engine.
- Optional fallback: `readpst` (libpst). macOS: `brew install libpst`; Debian/Ubuntu: `apt install pst-utils`.

## Usage

Data (SQLite database, logs) lives in `~/Library/Application Support/MailArchiveExplorer` (macOS), `%APPDATA%\MailArchiveExplorer` (Windows) or `~/.local/share/MailArchiveExplorer` (Linux). Set `MAE_DATA_DIR` to move it.

- **Add an archive**: background import (cancellable; an interrupted import resumes when you add the archive again).
- **Unload the archive**: select the archive (or one of its folders) in the tree, then use the toolbar button or the right-click menu. It removes the archive from the index; the source file is never touched and can be reloaded.
- **Export ▾** (or right-click in the list): `.eml` (one file per message), a single `.mbox`, attachments, search results as `.csv`. Applies to the selection, or to all results of the current view if nothing is selected. An export never overwrites an existing file.
- **Attachments**: double-click to save (sanitized name). The viewer shows text or HTML.
- **Back up the database**: uses the SQLite backup API, consistent even while open. To restore: close the app, replace `archive.db` with the copy and delete `archive.db-wal` / `-shm`.

### Formats

| Format | Reader | Note |
|---|---|---|
| PST / OST | `pypff` (fallback `readpst`) | see `docs/PST_FEASIBILITY.md` |
| OLM (Outlook for Mac) | `readers/olm_reader.py` (ZIP + XML) | standard library only |
| MBOX, EML | standard library | MBOX read by byte offsets (large files) |

### Search

Words, `"exact phrases"`, `AND` / `OR` / `NOT` (uppercase), parentheses, trailing wildcard `word*`, fields `from:` `to:` `subject:` `body:` `pj:` (French aliases `de:` `objet:` `corps:` `fichier:`), filters `before:YYYY-MM-DD` `after:YYYY-MM-DD` `has:attachment`. Invalid input shows a clear message, never a raw SQL error.

## Security

Archives are **untrusted input**. Main protections:

- **Message HTML**: sanitized (`link`, `base`, `meta`, `script`, `iframe`, `object`, `embed`… removed), strict CSP, JavaScript disabled, all network access blocked, remote images blocked by default (explicit opt-in, limited to the current message), external links need confirmation. Automated check: the self-test verifies that a `preconnect` link makes no network connection.
- **Attachments and exports**: sanitized names (path traversal, Windows reserved names, symlinks), never overwrites, never executes; CSV is protected against formula injection; EML headers are protected against injection.
- **Search**: parameterized queries only; input is converted to escaped FTS5 syntax.
- **Formats**: memory limits on OLM XML and MBOX messages, XML with a `DOCTYPE` is rejected, paths taken from an archive are never used on disk.
- **Build chain**: GitHub Actions pinned by commit SHA, least-privilege permissions, exact build dependencies, provenance attestation.

The code received an independent security review (its findings were fixed or documented). This is not a substitute for a professional audit or for testing with genuinely hostile files. To report a vulnerability, use the repository's *Security* tab (private reporting) rather than a public issue.

## Development

```bash
.venv/bin/python -m pytest                              # tests (PST/OLM tests are skipped when files are absent)
.venv/bin/python -m mail_archive_explorer --selftest    # pypff, FTS5, import/search, WebEngine
```

PST tests use **real public files** placed in `tests/fixtures/private/` (git-ignored, as are `*.pst`, `*.ost`, `*.olm`); CI downloads them with SHA-256 verification (sources: `docs/PST_FEASIBILITY.md` §4). An OLM test expects `tests/fixtures/private/mac_archive.olm` (a personal archive: never commit it). MBOX/EML fixtures are generated by `tools/make_fixtures.py`.

Local executable build: `pip install -r requirements-build.txt && pip install --no-deps -e .`, then `cd packaging && pyinstaller --noconfirm mail_archive_explorer.spec`. CI (`.github/workflows/`) runs the tests on Ubuntu, macOS and Windows; pushing a `v*` tag builds and publishes the executables (after tests, with a self-test of the packaged app).

## Known limitations

- Developed on macOS. CI runs the tests and the packaged-app self-test on Windows and Linux, but **interactive use** of the interface is not verified there.
- **PST**: validated on small public files; throughput and memory on multi-GB archives are unmeasured. Only e-mails are imported (not contacts, calendars, tasks). An embedded message attachment is extracted in raw form.
- **OLM**: reader written from a single real file; depending on the archive, many messages only have a preview (not the full body) and most inline images have no content. Dates are assumed to be UTC.
- **Export**: EML for PST/OLM messages is reconstructed (original transport headers are absent); MBOX/EML sources are re-exported byte for byte.
- Import runs in a thread of the application (not a separate process); no deduplication UI (duplicates are detected and kept); unsigned executables.

## License

Distributed under the **GNU GPL v3 or later** ([LICENSE](LICENSE)). Dependency licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); all are compatible with GPLv3. `readpst` (libpst, GPL) is called as an external program and is not bundled in the executables.
