"""Internationalisation minimale : les chaînes sources sont en français, `tr()` les traduit.

- Langues : « fr » (source) et « en ». Le choix est appliqué au démarrage (changement = redémarrage).
- `tr("texte {x}")` renvoie le texte tel quel en français, sa traduction en anglais ; les champs
  `{x}` se remplissent ensuite avec `.format(...)`. Une chaîne absente du dictionnaire reste en français
  (un test vérifie qu'aucune chaîne passée à tr() n'est oubliée)."""
from __future__ import annotations

SUPPORTED = ("fr", "en")
_lang = "fr"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in SUPPORTED else "fr"


def language() -> str:
    return _lang


def resolve(preference: str | None, system_locale: str | None) -> str:
    """Préférence enregistrée ('fr', 'en' ou 'auto'/None) -> langue effective.
    En mode auto : français si la langue du système est le français, anglais sinon."""
    if preference in SUPPORTED:
        return preference
    return "fr" if (system_locale or "").lower().startswith("fr") else "en"


def tr(text: str) -> str:
    if _lang == "en":
        from .translations_en import EN
        return EN.get(text, text)
    return text
