# Mail Archive Explorer (MVP)

Application desktop **locale** pour consulter, indexer et rechercher des archives **PST/OST, OLM (Outlook pour Mac), MBOX et EML**. Aucune donnée ne quitte la machine ; les archives sources sont ouvertes en lecture seule et ne sont jamais modifiées. Résultats du spike PST : [docs/PST_FEASIBILITY.md](docs/PST_FEASIBILITY.md). Architecture : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Limites connues : voir plus bas.

## Installation

Python 3.12 ou plus (développé et testé sous 3.14, macOS arm64).

```bash
python3 -m venv .venv
.venv/bin/pip install --only-binary=:all: PySide6 libpff-python pytest
```

- `libpff-python` (module `pypff`) : wheel binaire, aucune dépendance native à installer. Moteur PST principal.
- Moteur de repli optionnel : `readpst` (libpst). macOS : `brew install libpst` ; Debian/Ubuntu : `apt install pst-utils`.

## Lancement

```bash
PYTHONPATH=src .venv/bin/python -m mail_archive_explorer
```

La base est créée dans `~/Library/Application Support/MailArchiveExplorer/archive.db` (macOS), `%APPDATA%\MailArchiveExplorer` (Windows) ou `~/.local/share/MailArchiveExplorer` (Linux). Variable `MAE_DATA_DIR` pour la changer.

Barre d'outils : *Ajouter une archive* (import en tâche de fond, annulable, reprenable), *Retirer de l'index*, *Sauvegarder la base*. Double-clic sur une pièce jointe : enregistrement (nom assaini).

## Formats

| Format | Lecteur | Remarque |
|---|---|---|
| PST / OST | `pypff` (repli `readpst`) | voir `docs/PST_FEASIBILITY.md` |
| OLM (Outlook pour Mac) | `readers/olm_reader.py` (ZIP + XML, bibliothèque standard) | pas de dépendance supplémentaire |
| MBOX, EML | bibliothèque standard | |

## Export

Menu **Exporter ▾** (ou clic droit dans la liste) : messages en `.eml` (un fichier par message), en un fichier `.mbox`, pièces jointes, résultats de recherche en `.csv`. S'applique à la sélection, ou à tous les résultats de la vue courante si rien n'est sélectionné. Tourne en arrière-plan, annulable. Les messages venant de MBOX/EML sont réexportés à l'identique ; ceux de PST/OLM sont reconstruits (voir « Limites connues »).

## Décharger une archive

Sélectionner l'archive (ou un de ses dossiers) dans l'arbre, puis **Décharger l'archive** (barre d'outils ou clic droit). Retire l'archive de l'index ; le fichier source n'est jamais touché et peut être rechargé.

## Recherche

Mots, `"expressions exactes"`, `AND` / `OR` / `NOT` (majuscules), parenthèses, joker final `mot*`, champs `from:` `to:` `subject:` `body:` `pj:` (alias français `de:` `objet:` `corps:` `fichier:`), filtres `before:AAAA-MM-JJ` `after:AAAA-MM-JJ` `has:attachment`. Les accents sont ignorés. Une saisie invalide affiche un message clair, jamais une erreur SQL.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest
```

Les tests PST utilisent de **vrais fichiers publics** placés dans `tests/fixtures/private/` (ignoré par git, ainsi que `*.pst`, `*.ost`, `*.olm`) ; ils sont sautés si absents. Le test OLM attend `tests/fixtures/private/mac_archive.olm` (archive personnelle : ne jamais la commiter). Sources : voir `docs/PST_FEASIBILITY.md` §4. Les fixtures MBOX/EML sont générées par `tools/make_fixtures.py`.

## Sauvegarde / restauration de la base

Menu *Sauvegarder la base…* (API `sqlite3.Connection.backup`, cohérente même base ouverte). Restauration : fermer l'application et remplacer `archive.db` (et supprimer `archive.db-wal` / `-shm`) par la copie.

## Exécutables autonomes

Construits par GitHub Actions (`.github/workflows/release.yml`) : poser une étiquette (`git tag v0.1.0 && git push --tags`) produit un `.zip` Windows et un `.dmg` macOS (Apple Silicon) attachés à la release. Aucune installation de Python n'est nécessaire. La release n'est construite que si les tests des 3 systèmes passent ; les actions GitHub sont épinglées par empreinte, les dépendances de build par version exacte (`requirements-build.txt`), et chaque fichier publié porte une attestation de provenance : `gh attestation verify <fichier> --repo f-peng/MailArchiveExplorer`.

En local : `pip install -e . pyinstaller`, puis `cd packaging && pyinstaller --noconfirm mail_archive_explorer.spec`. Vérification de l'application packagée : `MailArchiveExplorer --selftest` (pypff, FTS5, import/recherche, rendu HTML).

Les exécutables **ne sont pas signés** : Windows (SmartScreen) et macOS (Gatekeeper) demandent une confirmation au premier lancement. macOS : clic droit sur l'application puis *Ouvrir*, ou `xattr -dr com.apple.quarantine MailArchiveExplorer.app`. Taille : environ 500 Mo décompressés (Qt WebEngine).

## Limites connues

- Développé et testé sur macOS ; **Windows et Linux ne sont pas vérifiés** (la CI les exerce, sans garantie).
- **PST** : validé sur de petits fichiers publics ; débit et mémoire sur des archives de plusieurs Go non mesurés. Seuls les e-mails sont importés (pas contacts, agendas, tâches). Un message incorporé en pièce jointe est extrait sous forme brute.
- **OLM** : lecteur écrit d'après un seul fichier réel ; selon l'archive, beaucoup de messages n'ont qu'un aperçu et non leur corps complet, et la plupart des images incorporées n'ont pas leur contenu. Dates supposées en UTC.
- **Export** : l'EML des messages PST/OLM est reconstruit (en-têtes de transport d'origine absents).
- Import dans un fil d'exécution de l'application (pas un processus séparé) ; pas d'interface de dédoublonnage (les doublons sont détectés et conservés) ; interface non traduite ; exécutables non signés.

## Licence

Mail Archive Explorer est distribué sous **GNU GPL v3 ou ultérieure** (voir [LICENSE](LICENSE)). Les licences des dépendances sont listées dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) ; toutes sont compatibles avec la GPL v3. `readpst` (libpst, GPL) est appelé comme programme externe et n'est pas embarqué dans les exécutables.
