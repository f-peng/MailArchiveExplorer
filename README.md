# Mail Archive Explorer

🇫🇷 Français · [🇬🇧 English](README.en.md)

Application de bureau **100 % locale** pour consulter, indexer et rechercher des archives de messagerie : **PST/OST, OLM (Outlook pour Mac), MBOX et EML**.

- Aucune donnée ne quitte la machine ; les archives sources sont ouvertes en **lecture seule** et ne sont jamais modifiées.
- Import en arrière-plan, annulable et reprenable ; recherche plein texte (accents ignorés) ; tri par colonne ; thèmes clair et sombre.
- Export en EML, MBOX, CSV et pièces jointes.
- Interface en **français et anglais** (bouton 🌐 *Langue / Language*, appliqué au redémarrage ; automatique par défaut selon la langue du système). Menu **À propos** : version et détails copiables pour un rapport de bug.

> **Statut : pré-version (`v0.1.1-rc3`).** Utilisable, mais jeune : voir « Limites connues ».

Documentation technique : [spike PST](docs/PST_FEASIBILITY.md) · [architecture](docs/ARCHITECTURE.md).

## Installation

### Exécutables (aucun Python requis)

Téléchargez le fichier de votre système depuis la page [Releases](https://github.com/f-peng/MailArchiveExplorer/releases) :

| Système | Fichier |
|---|---|
| macOS (Apple Silicon) | `MailArchiveExplorer-macos-arm64.dmg` |
| Windows (x64) | `MailArchiveExplorer-windows-x64.zip` (à décompresser) |
| Linux (x64) | `MailArchiveExplorer-linux-x64.tar.gz` (à décompresser, lancer `MailArchiveExplorer/MailArchiveExplorer`) — *en cours de validation* |

Sous Linux, installez au besoin les bibliothèques Qt/Chromium (Debian/Ubuntu : `libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libnss3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxcursor1 libxi6 libfontconfig1 libasound2`).

Les exécutables **ne sont pas signés** : Windows (SmartScreen) et macOS (Gatekeeper) demandent une confirmation au premier lancement.
- macOS : clic droit sur l'application puis *Ouvrir*, ou `xattr -dr com.apple.quarantine MailArchiveExplorer.app`.
- Windows : *Informations complémentaires* puis *Exécuter quand même*.

Taille : environ 500 Mo décompressés (Qt WebEngine). Chaque fichier publié porte une attestation de provenance : `gh attestation verify <fichier> --repo f-peng/MailArchiveExplorer`.

### Depuis les sources

Python 3.12 ou plus (développé sous 3.14).

```bash
git clone https://github.com/f-peng/MailArchiveExplorer.git
cd MailArchiveExplorer
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m mail_archive_explorer
```

- `libpff-python` (module `pypff`) est un wheel binaire, sans dépendance native. C'est le moteur PST principal.
- Repli optionnel : `readpst` (libpst). macOS : `brew install libpst` ; Debian/Ubuntu : `apt install pst-utils`.

## Utilisation

Les données (base SQLite, journaux) sont stockées dans `~/Library/Application Support/MailArchiveExplorer` (macOS), `%APPDATA%\MailArchiveExplorer` (Windows) ou `~/.local/share/MailArchiveExplorer` (Linux). La variable `MAE_DATA_DIR` permet de les déplacer.

- **Ajouter une archive** : import en arrière-plan (annulable ; une interruption se reprend en ré-ajoutant l'archive).
- **Décharger l'archive** : sélectionnez l'archive (ou un de ses dossiers) dans l'arbre, puis le bouton ou le clic droit. Retire l'archive de l'index ; le fichier source n'est jamais touché et peut être rechargé.
- **Exporter ▾** (ou clic droit dans la liste) : `.eml` (un fichier par message), un fichier `.mbox`, pièces jointes, résultats de recherche en `.csv`. S'applique à la sélection, ou à tous les résultats de la vue si rien n'est sélectionné. Un export ne remplace jamais un fichier existant.
- **Pièces jointes** : double-clic pour enregistrer (nom assaini). Le visualiseur affiche le texte ou le HTML.
- **Sauvegarder la base** : API de sauvegarde SQLite, cohérente base ouverte. Restauration : fermer l'application, remplacer `archive.db` par la copie et supprimer `archive.db-wal` / `-shm`.

### Formats

| Format | Lecteur | Remarque |
|---|---|---|
| PST / OST | `pypff` (repli `readpst`) | voir `docs/PST_FEASIBILITY.md` |
| OLM (Outlook pour Mac) | `readers/olm_reader.py` (ZIP + XML) | bibliothèque standard uniquement |
| MBOX, EML | bibliothèque standard | MBOX lu par décalages d'octets (gros fichiers) |

### Recherche

Mots, `"expressions exactes"`, `AND` / `OR` / `NOT` (majuscules), parenthèses, joker final `mot*`, champs `from:` `to:` `subject:` `body:` `pj:` (alias `de:` `objet:` `corps:` `fichier:`), filtres `before:AAAA-MM-JJ` `after:AAAA-MM-JJ` `has:attachment`. Une saisie invalide affiche un message clair, jamais une erreur SQL.

## Sécurité

Les archives sont des entrées **non fiables**. Principales protections :

- **HTML des messages** : assaini (suppression de `link`, `base`, `meta`, `script`, `iframe`, `object`, `embed`…), politique CSP stricte, JavaScript désactivé, tout accès réseau bloqué, images distantes bloquées par défaut (autorisation explicite et limitée au message courant), liens externes avec confirmation. Contrôle automatique : l'auto-test vérifie qu'un lien `preconnect` ne produit aucune connexion.
- **Pièces jointes et exports** : noms assainis (traversée de répertoire, noms réservés Windows, liens symboliques), jamais d'écrasement, jamais d'exécution ; CSV protégé contre l'injection de formules ; en-têtes d'EML à l'abri de l'injection.
- **Recherche** : requêtes paramétrées uniquement, saisie convertie en syntaxe FTS5 échappée.
- **Formats** : bornes mémoire sur les XML OLM et les messages MBOX, XML avec `DOCTYPE` refusé, chemins issus de l'archive jamais utilisés sur le disque.
- **Chaîne de construction** : actions GitHub épinglées par empreinte, droits minimaux, dépendances de build exactes, attestation de provenance.

Le code a fait l'objet d'une relecture de sécurité indépendante (ses constats ont été traités ou documentés). Elle ne remplace pas un audit professionnel ni un test sur des fichiers réellement hostiles. Pour signaler une vulnérabilité, utilisez l'onglet *Security* du dépôt (signalement privé) plutôt qu'une issue publique.

## Développement

```bash
.venv/bin/python -m pytest                       # tests (les tests PST/OLM sont sautés si les fichiers sont absents)
.venv/bin/python -m mail_archive_explorer --selftest   # pypff, FTS5, import/recherche, WebEngine
```

Les tests PST utilisent de **vrais fichiers publics** placés dans `tests/fixtures/private/` (ignoré par git, ainsi que `*.pst`, `*.ost`, `*.olm`) ; la CI les télécharge avec vérification SHA-256 (sources : `docs/PST_FEASIBILITY.md` §4). Un test OLM attend `tests/fixtures/private/mac_archive.olm` (archive personnelle : ne jamais la commiter). Les fixtures MBOX/EML sont générées par `tools/make_fixtures.py`.

Build local des exécutables : `pip install -r requirements-build.txt && pip install --no-deps -e .`, puis `cd packaging && pyinstaller --noconfirm mail_archive_explorer.spec`. La CI (`.github/workflows/`) exécute les tests sur Ubuntu, macOS et Windows ; poser une étiquette `v*` construit et publie les exécutables (après tests, avec auto-test de l'application packagée).

## Limites connues

- Développé sur macOS. La CI exécute les tests et l'auto-test de l'application packagée sur Windows et Linux, mais l'**usage interactif** de l'interface n'y est pas vérifié.
- **PST** : validé sur de petits fichiers publics ; débit et mémoire sur des archives de plusieurs Go non mesurés. Seuls les e-mails sont importés (pas contacts, agendas, tâches). Un message incorporé en pièce jointe est extrait sous forme brute.
- **OLM** : lecteur écrit d'après un seul fichier réel ; selon l'archive, beaucoup de messages n'ont qu'un aperçu (et non leur corps complet) et la plupart des images incorporées n'ont pas leur contenu. Dates supposées en UTC.
- **Export** : l'EML des messages PST/OLM est reconstruit (en-têtes de transport d'origine absents) ; MBOX/EML sources sont réexportés à l'identique.
- L'import tourne dans un fil de l'application (pas un processus séparé) ; pas d'interface de dédoublonnage (les doublons sont détectés et conservés) ; exécutables non signés.

## Licence

Distribué sous **GNU GPL v3 ou ultérieure** ([LICENSE](LICENSE)). Les licences des dépendances sont dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) ; toutes sont compatibles avec la GPL v3. `readpst` (libpst, GPL) est appelé comme programme externe et n'est pas embarqué dans les exécutables.
