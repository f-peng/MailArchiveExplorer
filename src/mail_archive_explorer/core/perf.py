"""Journalise les opérations lentes (diagnostic « ça rame » sans instrumenter à la main)."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager

log = logging.getLogger("perf")


@contextmanager
def timed(label: str, threshold: float = 0.25):
    t = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t
        if dt >= threshold:
            log.warning("LENT %s : %.0f ms", label, dt * 1000)
