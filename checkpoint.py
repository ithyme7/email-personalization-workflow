from __future__ import annotations

import json
import threading
from pathlib import Path


_lock = threading.Lock()


def _checkpoint_path(output_path: Path | str) -> Path:
    """Retourneert het checkpoint-bestandspad naast de output."""
    path = Path(output_path)
    return path.parent / f"{path.stem}_checkpoint{path.suffix}"


def load_checkpoint(output_path: Path | str) -> dict[int, dict]:
    """Laadt reeds verwerkte rows uit een checkpoint-bestand.

    Retourneert een dict geïndexeerd op 1-based positie in de originele
    leid, zodat deze direct in ``rows_by_index`` kan worden geplaatst.
    """
    ckpt = _checkpoint_path(output_path)
    if not ckpt.exists():
        return {}
    try:
        data = json.loads(ckpt.read_text(encoding="utf-8"))
        # JSON keys zijn strings -> converteer terug naar int
        return {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def save_checkpoint(rows_by_index: dict[int, dict], output_path: Path | str) -> None:
    """Schrijft de huidige voortgang naar een checkpoint-bestand (thread-safe).

    Interne velden (prefixed met ``_``) worden genegeerd bij het serialiseren
    omdat die louter runtime-helpers zijn.
    """
    with _lock:
        ckpt = _checkpoint_path(output_path)
        data: dict[str, dict] = {}
        for idx, row in rows_by_index.items():
            clean_row = {k: v for k, v in row.items() if not k.startswith("_")}
            data[str(idx)] = clean_row
        ckpt.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_checkpoint(output_path: Path | str) -> None:
    """Verwijdert het checkpoint-bestand na succesvolle voltooiing."""
    ckpt = _checkpoint_path(output_path)
    if ckpt.exists():
        ckpt.unlink()