# PST_FEASIBILITY : résultats du spike PHASE 0

Date : 2026-11-07. Tout ce qui suit a été exécuté sur cette machine ; rien n'est supposé.

## 1. Verdict

| Voie | Verdict | Rôle recommandé |
|---|---|---|
| `pypff` (libpff, paquet PyPI `libpff-python`) | **Faisable** : wheels binaires installés et fonctionnels, arborescence, messages, corps, destinataires, pièces jointes lus sur de vrais PST. | **Moteur principal** |
| `readpst` (libpst 0.6.76, Homebrew) | **Faisable** : conversion réussie sur les 3 fichiers. | **Repli** (et outil de recoupement en test) |

**Limite majeure de la validation** : les seuls PST publics obtenus sont minuscules (7 messages au maximum). Le débit sur de gros volumes **n'a pas pu être mesuré** (voir §5). Un PST réel de plusieurs centaines de Mo/Go est nécessaire avant de valider la PHASE 3.

## 2. Environnement testé

- macOS 27.0.1 (Darwin 27.0.0), arm64 (Apple Silicon), Xcode installé, Homebrew 7.0.12.
- Pythons présents : 3.15.2 et 3.14.10 (Homebrew), 3.11.14 (pyenv). **Pas de 3.12 ni 3.13**. `/usr/bin/python3` système non utilisé.
- `pypff` testé sur 3.11, 3.14 et 3.15 (venvs jetables, hors dépôt) : même résultat, `import pypff` OK, `pypff.get_version()` = `20260926`.
- PySide6 6.12.0 : wheel `cp310-abi3` universel macOS disponible, téléchargeable pour 3.11, 3.14, 3.15 (installation non effectuée, hors périmètre PHASE 0).

## 3. Installation

```bash
# pypff : wheel binaire, aucune compilation, aucune dépendance native à installer
python -m pip install --only-binary=:all: libpff-python      # version testée : 20260926
python -I -c "import pypff; print(pypff.get_version())"

# readpst (macOS)
brew install libpst                                          # version testée : 0.6.76
readpst -V
# Debian/Ubuntu : apt install pst-utils    ·   Windows : pas de binaire officiel simple (voir §6)
```

Disponibilité des wheels `libpff-python` 20260926 vérifiée (téléchargement réel avec `pip download --platform`) pour **win_amd64**, **manylinux_2_28_x86_64** et **macosx arm64**, en CPython 3.12, 3.13 et 3.14. L'installation et l'exécution n'ont été testées que sur macOS arm64. Le comportement sous Windows n'est pas vérifié.

Le paquet `pypff` de PyPI (1.0.4) est un autre paquet, plus ancien : ne pas l'utiliser. Le bon nom est **`libpff-python`**, qui expose le module `pypff`. Versions disponibles : 20161119, 20211114, 20231205, 20260926.

## 4. Jeux de test réels (hors dépôt)

Téléchargés dans le répertoire de travail temporaire, jamais commités. Empreintes SHA-256 vérifiées identiques avant et après tous les tests (lecture seule confirmée).

| Fichier | Source | Taille | Contenu |
|---|---|---|---|
| `dist-list.pst` | github.com/rjohnsondev/java-libpst, `src/test/resources` | 265 Ko | PST Outlook 2003+ : 1 rendez-vous (2 PJ), 2 contacts |
| `tika_testPST.pst` | github.com/apache/tika (`testPST.pst`) | 2,2 Mo | 7 e-mails réels (dossiers en français), 1 PJ |
| `example-2013.ost` | java-libpst, `src/test/resources` | 16 Mo | OST Outlook 2013, 3 e-mails, ~45 dossiers |

Outil : [`tools/pst_spike.py`](../tools/pst_spike.py) (diagnostic, pas le futur lecteur).

## 5. Résultats constatés

**pypff**
- Ouverture quasi instantanée (1-2 ms, fichier ouvert paresseusement). Signature, `content_type` (112 = PST, 111 = OST), chiffrement détectés.
- Arborescence complète parcourue, noms de dossiers localisés (« Éléments supprimés », « Début du fichier de données Outlook ») corrects en Unicode.
- Par message : objet, nom d'expéditeur, date de livraison / d'envoi, destinataires, corps texte, HTML, RTF, en-têtes de transport (quand présents) lus sans erreur. 0 erreur sur les 3 fichiers.
- Pièces jointes : taille et octets lus correctement (`read_buffer`), SHA-256 calculable en flux.
- Débit : micro-benchmark sur `tika_testPST.pst` (7 messages, 500 passes, tout lu y compris PJ) : environ 3 200 msg/s, 9 Mo/s de corps. **Ce chiffre est un plancher de bruit** : fichier de 2 Mo entièrement en cache OS, messages minuscules. Il ne se transpose pas à un PST de 50 Go.
- Fichier vide : `OSError` explicite. Fichier tronqué à 50 % : ouverture et lecture des 7 messages sans erreur (les données lues étaient apparemment dans la partie conservée) : **test de corruption non concluant**, à refaire en PHASE 3 avec un PST plus gros et plusieurs types de dommages.

**readpst**
- `readpst -r -e -8` produit un `.eml` par message, dans une arborescence de dossiers. 7 EML pour `tika_testPST.pst` (cohérent avec pypff), calendrier en `.ics`, contacts en `.vcf`.
- Durée : environ 17 ms par fichier de 2 Mo (20 exécutions en 0,35 s, démarrage de processus inclus). Même réserve : non représentatif.
- Fichier tronqué : 7 fichiers produits, code retour 0, **aucun signal d'erreur exploitable** (à tenir compte : il faudra parser stderr).

## 6. Limites constatées et risques techniques

1. **Items non-courriel** : contacts, rendez-vous, notes sont renvoyés par pypff comme `pypff.item` génériques, sans `get_subject`, etc. Le lecteur doit filtrer (`hasattr` ou classe de message MAPI `PR_MESSAGE_CLASS` 0x001A) et ignorer ou traiter à part. L'accès MAPI brut passe par `record_sets` / `entries` (type d'entrée + `data`).
2. **Pas de destinataire « prêt à l'emploi »** : `message.recipients` donne des entrées MAPI à décoder (identifiants MAPI **vérifiés** pendant le MVP sur les fichiers de test : adresse 0x3003, SMTP 0x39FE, nom 0x3001, type To/CC/BCC 0x0C15 ; classe de message 0x001A ; Message-ID 0x1035). À encapsuler dans la couche d'abstraction.
3. **Nom de pièce jointe** : `get_long_filename()` renvoie `None` sur certaines PJ. Repli requis sur les propriétés 0x3707/0x3704, puis 0x3001 (nom d'affichage, observé : « First email »). Une PJ du jeu Tika est un **message incorporé** (`PR_ATTACH_METHOD` 0x3705 = 5) : ses octets lus ne sont pas un fichier mais un blob interne ; il faudra décider (exporter en `.eml`/`.msg`, ou l'ouvrir en sous-message).
4. **MIME de PJ** : propriété 0x370E absente sur les PJ testées ; type à déduire de l'extension (`mimetypes`) ou du contenu.
5. **En-têtes de transport absents** sur certains messages (rendez-vous, messages envoyés/brouillons) : expéditeur et destinataires doivent venir des propriétés MAPI, pas seulement des en-têtes.
6. **Expéditeur** : `get_sender_name()` donne le nom (« Unknown » pour un rendez-vous) ; l'adresse SMTP se lit en 0x5D01 / 0x0C1F (parfois X.500 `/O=...`, constaté) avec repli sur les en-têtes, avec traitement des adresses Exchange (X.500 `/O=...`).
7. **RTF compressé** : `get_rtf_body()` fonctionne (9 753 octets sur le rendez-vous) ; conversion RTF vers HTML/texte à prévoir (bibliothèque tierce ou module maison).
8. **Encodage du corps** : `get_plain_text_body()` renvoie des `bytes`, jamais du `str`. Il faut déduire le jeu de caractères (page de code du message / du fichier : `file.ascii_codepage`) puis décoder avec repli `errors="replace"`.
9. **Fichiers volumineux** : non testés (plus gros fichier : 16 Mo). Comportement mémoire, vitesse et robustesse sur PST de plusieurs Go : **inconnus**.
10. **PST protégés par mot de passe** : `passworded.pst` existe dans java-libpst mais n'a pas été testé. Comportement de libpff face à un PST protégé : non testé (fichier non téléchargé).
11. **libpff est LGPL**, maintenu en sorties datées (dernière 2026-09-26) : mieux maintenu qu'on pourrait le craindre, mais mainteneur unique.
12. **readpst** : pas de lecture à la demande (conversion intégrale sur disque : espace temporaire ≈ taille du PST ou plus), pas de binaire Windows officiel, codes retour peu fiables, GPL (libpst est GPL-2+ : vérifier la compatibilité avant toute distribution d'un exécutable embarquant `readpst`; l'appeler comme programme externe séparé limite le risque, à valider juridiquement).
13. **Python 3.15** présent mais très récent : des dépendances de packaging (PyInstaller) peuvent ne pas suivre.

## 7. Recommandation

- **Moteur principal** : `pypff` via `libpff-python`, épinglé (`libpff-python==20260926`), lecture directe, générateurs, PJ à la demande.
- **Repli** : `readpst -r -e -8` en sous-processus vers un répertoire temporaire, ingéré par le lecteur EML, avec provenance PST + dossier conservée. Sélection automatique si `import pypff` échoue ou si un PST fait lever des erreurs fatales à pypff ; forçable par configuration.
- **Python** : **3.14** pour le développement (présent, wheels pypff OK, PySide6 abi3 OK). Plancher déclaré : 3.12. Éviter 3.15 tant que PyInstaller n'est pas validé.
- **Avant la PHASE 3** : obtenir un PST réel de plusieurs centaines de Mo au minimum (idéalement un PST Outlook fourni par vous, avec PJ nombreuses, HTML, RTF, plusieurs encodages, éventuellement endommagé), conservé hors dépôt, pour mesurer le vrai débit et tester la corruption.
