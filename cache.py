from __future__ import annotations

import hashlib
from pathlib import Path

from config import CACHE_DIR


def cache_path(url: str, *, prefix: str = "") -> Path:
    """Berekent een uniek cache-bestandspad voor een URL.

    Zonder prefix: universele web-cache (gedeeld door web_research en deep_research).
    Met prefix: naamruimte voor specifieke data (bijv. 'deep:', 'rendered:').
    """
    key = f"{prefix}{url}" if prefix else url
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"