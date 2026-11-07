"""Choix automatique du moteur PST (forçable)."""
from __future__ import annotations

from pathlib import Path

from .pypff_engine import PypffEngine
from .readpst_engine import ReadpstEngine

ENGINES = {"pypff": PypffEngine, "readpst": ReadpstEngine}


def choose_engine(path: str | Path, forced: str | None = None):
    """Retourne une instance de moteur. `forced` : 'pypff' | 'readpst' | None (auto)."""
    path = Path(path)
    if forced:
        cls = ENGINES[forced]
        if not cls.is_available():
            raise RuntimeError(f"Moteur '{forced}' demandé mais indisponible.")
        return cls(path)
    if PypffEngine.is_available() and PypffEngine.probe(path).valid:
        return PypffEngine(path)
    if ReadpstEngine.is_available():
        return ReadpstEngine(path)
    raise RuntimeError("Aucun moteur PST utilisable (pypff invalide/absent, readpst absent).")
