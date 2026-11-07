# Dépendances tierces

Versions relevées dans l'environnement de développement (`pip` / métadonnées des paquets). Les textes complets des licences sont fournis avec chaque paquet installé (et dans les exécutables, dossier de chaque bibliothèque).

| Composant | Version | Licence | Usage |
|---|---|---|---|
| PySide6 / shiboken6 (Qt for Python) | 6.12.0 | LGPL-3.0-only OU GPL-3.0-only (double licence) | interface, Qt WebEngine ; liaison dynamique |
| Qt 6 (embarqué par les wheels PySide6) | 6.12.0 | LGPL-3.0 / GPL-3.0 selon module | |
| Chromium (Qt WebEngine) | version de Qt | BSD et licences tierces diverses (voir `Qt WebEngine Licenses`) | rendu HTML |
| libpff-python (`pypff`, libpff) | 20260926 | LGPL-3.0-or-later | lecture PST/OST |
| readpst (libpst) | 0.6.76 | GPL-2.0-or-later | moteur de repli **externe, non embarqué** |
| Python | 3.14 | PSF License | interpréteur (embarqué par PyInstaller) |
| PyInstaller | (build uniquement) | GPL-2.0 avec exception de distribution | construction des exécutables |

## Obligations (résumé non juridique)
- Projet GPL-3.0-or-later : les sources correspondant à chaque exécutable distribué sont celles du dépôt à l'étiquette de version.
- LGPL (PySide6, libpff) : les bibliothèques sont liées dynamiquement, non modifiées, et remplaçables par l'utilisateur dans le dossier de l'application.
- Les fichiers de test PST/OST publics utilisés en local (java-libpst, Apache Tika) ne sont **pas** redistribués dans ce dépôt.
