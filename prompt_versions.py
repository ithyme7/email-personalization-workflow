from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from config import PROMPTS_DIR


PROMPT_FILES = {
    "evidence_prompt_hash": "evidence_extraction.txt",
    "write_prompt_hash": "write_personalization.txt",
    "qc_prompt_hash": "qc_personalization.txt",
}


def file_sha256(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def prompt_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for key, filename in PROMPT_FILES.items():
        path = PROMPTS_DIR / filename
        hashes[key] = file_sha256(path) if path.exists() else ""
    material = json.dumps(hashes, sort_keys=True).encode("utf-8")
    hashes["prompt_set_hash"] = hashlib.sha256(material).hexdigest()
    return hashes


def tone_profile_hash(tone_profile_payload: dict[str, Any]) -> str:
    material = json.dumps(tone_profile_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
