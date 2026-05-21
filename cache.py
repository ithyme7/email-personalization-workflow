from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from config import CACHE_DIR

logger = logging.getLogger(__name__)


def cache_path(url: str, *, prefix: str = "") -> Path:
    """Berekent een uniek cache-bestandspad voor een URL.

    Zonder prefix: universele web-cache (gedeeld door web_research en deep_research).
    Met prefix: naamruimte voor specifieke data (bijv. 'deep:', 'rendered:').
    """
    key = f"{prefix}{url}" if prefix else url
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _get_ttl() -> int:
    """Leest cache TTL uit de environment, of gebruik de standaard (24 uur)."""
    import os

    try:
        return int(os.getenv("CACHE_TTL_SECONDS", str(86400)))
    except ValueError:
        return 86400


def write_cached_json(path: Path, data: dict) -> None:
    """Schrijft data naar een cache-bestand met een TTL-tijdstempel.

    De `_cached_at` key wordt automatisch toegevoegd aan een kopie van `data`.
    """
    data_to_write = dict(data)
    data_to_write["_cached_at"] = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data_to_write, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_cached_json(path: Path, ttl_seconds: int | None = None) -> dict | None:
    """Leest een JSON cache-bestand met TTL-controle.

    Returns:
        dict als het bestand bestaat en niet verlopen is, anders None.
        Bestanden zonder `_cached_at` (oud formaat) worden als geldig behandeld.
        Verlopen bestanden worden automatisch verwijderd.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if ttl_seconds is not None:
        cached_at = data.get("_cached_at")
        if cached_at is not None:
            age = time.time() - cached_at
            if age > ttl_seconds:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                logger.debug(
                    "Cache expired: %s (leeftijd: %.0fs, TTL: %ds)",
                    path.name,
                    age,
                    ttl_seconds,
                )
                return None
        # Geen _cached_at = oud formaat → beschouw als geldig
    return data


def clean_expired_cache(ttl_seconds: int | None = None) -> int:
    """Verwijdert alle verlopen cache-bestanden uit data/cache/.

    Returns:
        Aantal verwijderde bestanden.
    """
    if not CACHE_DIR.exists():
        return 0
    if ttl_seconds is None:
        ttl_seconds = _get_ttl()

    removed = 0
    for cache_file in list(CACHE_DIR.glob("*.json")):
        if not cache_file.is_file():
            continue
        # read_cached_json verwijdert verlopen bestanden automatisch
        data = read_cached_json(cache_file, ttl_seconds=ttl_seconds)
        if data is None:
            removed += 1
    return removed