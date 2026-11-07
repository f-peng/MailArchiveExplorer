"""Contrat des moteurs PST."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..base_reader import BaseReader


@dataclass(frozen=True)
class ProbeResult:
    valid: bool
    kind: str | None = None       # "PST" | "OST" | None
    size: int = 0
    encrypted: bool = False
    detail: str = ""


class PstEngine(BaseReader, Protocol):
    name: str

    @classmethod
    def is_available(cls) -> bool: ...
    @staticmethod
    def probe(path: Path) -> ProbeResult: ...
