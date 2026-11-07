# ARCHITECTURE : proposition PHASE 0 (à valider)

Statut : **proposition**. Aucun code d'implémentation n'existe. Les signatures de la §3 sont des contrats à valider, pas du code livré ; elles seront écrites en `Protocol`/ABC testables en PHASE 1.

## 1. Ajustements proposés à l'architecture initiale

| # | Ajustement | Raison (issue du spike) |
|---|---|---|
| A1 | `readers/pst_reader.py` + `pst_readpst_fallback.py` deviennent un sous-paquet `readers/pst/` : `engine.py` (Protocol `PstEngine`), `pypff_engine.py`, `readpst_engine.py`, `mapi.py` (décodage des propriétés, filtrage des classes de message, noms de PJ, destinataires), `rtf.py`, `selector.py`. | Les limites §6 de PST_FEASIBILITY (items non-courriel, noms de PJ, destinataires, RTF, encodage) sont de la logique MAPI à isoler et tester indépendamment du moteur. |
| A2 | Ajout `core/charset.py` (ou `services/text_decoding.py`) : décodage bytes vers str avec détection/repli. | pypff renvoie des `bytes` pour les corps. |
| A3 | Le repli `readpst` ne passe **pas** par `eml_reader` brut mais par un adaptateur `ReadpstEngine` qui parcourt l'arborescence de sortie et renvoie des `RawMessage` avec provenance (PST, chemin de dossier d'origine). | SPEC §3 impose de conserver la provenance. |
| A4 | `data/` sort de l'arborescence du paquet : répertoire utilisateur configurable (`platformdirs`), jamais dans le dépôt. | Évite les données personnelles dans le dépôt. |
| A5 | `tools/pst_spike.py` conservé comme outil de diagnostic. | Réutilisable pour débogage terrain. |
| A6 | Layout `src/mail_archive_explorer/` (au lieu de la racine du dépôt). | Imports fiables, tests sur le paquet installé, packaging propre. |
| A7 | Import exécuté dans un **processus séparé** (`multiprocessing` spawn) plutôt qu'un `QThread` pour le PST. | Le GIL est relâché par libpff de façon non garantie, un crash natif tuerait l'UI. Communication par file de messages (progression/erreurs). |
| A8 | Table `messages.message_class` + `kind` ajoutés ; le MVP n'importe que les e-mails (`IPM.Note*`), les autres classes sont comptées et journalisées. | Contacts/rendez-vous constatés dans les PST de test. |
| A9 | Pièces jointes de type message incorporé : stockées avec `attach_method` ; export en `.eml` best effort. | Cas observé dans `tika_testPST.pst`. |
| A10 | Python 3.14 en développement, plancher 3.12. | Voir PST_FEASIBILITY §7. |

Le reste de la section 2 est conservé.

## 2. Arborescence cible

```
PST_Viewer/
├── README.md  pyproject.toml  .gitignore
├── docs/                 PST_FEASIBILITY.md  ARCHITECTURE.md
├── src/mail_archive_explorer/
│   ├── main.py
│   ├── config/
│   ├── core/             models.py database.py migrations/ indexing.py search.py query_parser.py archive_manager.py charset.py
│   ├── readers/          base_reader.py mbox_reader.py eml_reader.py
│   │   └── pst/          engine.py pypff_engine.py readpst_engine.py mapi.py rtf.py selector.py
│   ├── services/         import_service.py attachment_service.py deduplication.py export_service.py hashing.py
│   ├── ui/               main_window.py archive_tree.py message_list.py message_viewer.py search_panel.py dialogs/
│   └── workers/          import_worker.py index_worker.py
├── tests/                unit/ integration/ fixtures/
└── tools/                pst_spike.py  (+ générateurs de fixtures synthétiques)
```

## 3. Interfaces entre modules (contrats à valider)

Dépendances autorisées : `ui` → `core`/`services`/`workers` ; `workers` → `services` ; `services` → `readers`, `core` ; `readers` → rien d'autre que `core.models`. `core` ne dépend d'aucun autre module. Aucun import de PySide6 hors de `ui/` et `workers/`.

**Modèles (`core/models.py`, dataclasses gelées)**
- `RawAddress(name: str | None, email: str | None)`
- `RawAttachment(index: int, filename: str | None, mime: str | None, size: int | None, content_id: str | None, is_inline: bool, attach_method: int | None, source_ref: object)` : aucun octet en mémoire.
- `RawMessage(source_id: str, folder_path: tuple[str, ...], message_id: str | None, subject: str | None, sender: RawAddress | None, to/cc/bcc: tuple[RawAddress, ...], sent_at: datetime | None, received_at: datetime | None, date_valid: bool, body_text: str | None, body_html: str | None, has_rtf: bool, headers: str | None, attachments: tuple[RawAttachment, ...], message_class: str | None, props: Mapping[str, object])`
- `FolderInfo(path: tuple[str, ...], message_count: int | None)`
- `ReadError(source_id, folder_path, stage, exception_type, detail)`

**`BaseReader` (Protocol)**
- `open() / close()` + context manager
- `list_folders() -> Iterator[FolderInfo]`
- `iter_messages(folder: FolderInfo) -> Iterator[RawMessage | ReadError]` (erreur par message renvoyée comme valeur, jamais levée)
- `open_attachment(att: RawAttachment) -> BinaryIO` (lecture à la demande, en flux)
- `reader_version: str`

**`PstEngine` (Protocol)** : mêmes opérations que `BaseReader` plus `name: str`, `is_available() -> bool`, `probe(path) -> ProbeResult` (valide, type PST/OST, taille, chiffrement). `selector.choose_engine(config, path)` renvoie `pypff` par défaut, `readpst` si indisponible ou forcé.

**`ImportService`**
- `import_archive(path, engine, progress: ProgressSink, cancel: CancelToken) -> ImportReport` ; transactions par lots de 500 ; idempotent ; écrit `import_checkpoints`.
- `ProgressSink` : `on_folder(path, total: int | None)`, `on_batch(done, errors)`. Pas de pourcentage si `total` inconnu.

**`Database`** : connexion unique en écriture (processus d'import), connexions lecture seule pour l'UI ; `apply_migrations()` via `PRAGMA user_version` ; `backup(dest)`.

**`SearchService`** : `search(query: str, filters: Filters, after: Keyset | None, limit: int) -> Page[SearchHit]` ; `query_parser.parse(str) -> ParsedQuery | QueryError`.

**`AttachmentService`** : `extract(message_id, index, dest_dir) -> Path` (nom assaini, anti-traversée) ; `hash_if_unknown(...)`.

## 4. Registre des risques

| # | Risque | Prob. | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Débit/mémoire de pypff sur PST de plusieurs Go **non mesuré** | Moyenne | Élevé | Obtenir un gros PST réel avant PHASE 3 ; benchmark dans les tests d'intégration ; générateurs et lots bornés |
| R2 | Crash natif de libpff sur fichier corrompu | Moyenne | Élevé | Import en processus séparé ; reprise par checkpoints ; repli readpst |
| R3 | Test de corruption non concluant | Haute | Moyen | Fabriquer plusieurs types de dommages sur un gros PST en PHASE 3 |
| R4 | Mainteneur unique de libpff ; pypff sans API de haut niveau pour destinataires/adresses | Moyenne | Moyen | Couche `mapi.py` testée ; version épinglée ; repli |
| R5 | Décodage de charset des corps (bytes) : texte corrompu | Moyenne | Moyen | `charset.py` + tests multi-encodages ; repli `replace` et indicateur de qualité |
| R6 | RTF compressé sans corps HTML/texte | Moyenne | Moyen | `rtf.py` ; choisir bibliothèque en PHASE 3 ; limite documentée |
| R7 | Packaging Windows : wheel pypff disponible mais non testé ; WebEngine lourd (>300 Mo) | Moyenne | Moyen | Évaluation dès PHASE 3 (SPEC §12) ; Windows en « si possible » |
| R8 | Licence GPL de libpst vs distribution | Faible/Moyenne | Moyen | `readpst` appelé comme programme externe, non embarqué par défaut ; avis juridique avant distribution |
| R9 | Python 3.15 trop récent pour PyInstaller/dépendances | Moyenne | Faible | Développer en 3.14, épingler ; CI sur 3.12 et 3.14 |
| R10 | Volumétrie base (1 M messages, centaines de Go) : taille FTS5/index | Moyenne | Élevé | Corps HTML en table séparée compressée, FTS external content ; test de charge PHASE 7 |
| R11 | Doublons par `content_hash` instables (dates invalides, corps modifiés) | Moyenne | Faible | Fonction documentée, testée, sans suppression automatique |
| R12 | Items non-courriel mélangés aux messages | Haute | Faible | Filtre sur `PR_MESSAGE_CLASS`, comptage dédié |
| R13 | Messages incorporés en PJ mal exportés | Moyenne | Faible | `attach_method` conservé ; limite documentée |
| R14 | Seuls 3 PST publics minuscules disponibles (aucune PJ « classique » ni HTML riche testés à grande échelle) | Haute | Moyen | Demander un PST utilisateur hors dépôt ; fixtures synthétiques pour MBOX/EML |
| R15 | Sécurité HTML (WebEngine) | Faible | Élevé | Mesures SPEC §6 ; tests dédiés en PHASE 5 |

## 5. Points à décider par vous

1. Valider A1 à A10, en particulier **A6** (layout `src/`) et **A7** (import en processus séparé).
2. Fournir (ou autoriser le téléchargement d'un) PST plus volumineux hors dépôt pour la PHASE 3.
3. Python 3.14 comme version de développement (3.12 absent de la machine).
