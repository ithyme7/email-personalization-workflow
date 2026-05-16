from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import TONE_PROFILES_DIR
from models import ToneProfile
from tone_preset_library import get_preset_profile, preset_names


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def available_tone_profiles() -> list[str]:
    names = set(preset_names())
    if not TONE_PROFILES_DIR.exists():
        return sorted(names)
    names.update(path.stem for path in TONE_PROFILES_DIR.glob("*.json"))
    return sorted(names)


def load_tone_profile(name_or_path: str = "friction_first") -> ToneProfile:
    value = (name_or_path or "friction_first").strip()
    path = Path(value)
    if not path.suffix:
        path = TONE_PROFILES_DIR / f"{value}.json"
    if not path.exists():
        preset = get_preset_profile(value)
        if preset:
            return preset
        fallback = TONE_PROFILES_DIR / "friction_first.json"
        if fallback.exists():
            path = fallback
        else:
            return ToneProfile(name=value or "default", description="Default conservative tone profile")

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return ToneProfile(
        name=str(raw.get("name", path.stem)).strip() or path.stem,
        description=str(raw.get("description", "")).strip(),
        opening_style=str(raw.get("opening_style", "")).strip(),
        custom_prompt=str(raw.get("custom_prompt", "")).strip(),
        angle_priorities=_as_list(raw.get("angle_priorities")),
        preferred_phrases=_as_list(raw.get("preferred_phrases")),
        banned_phrases=_as_list(raw.get("banned_phrases")),
        qc_focus=_as_list(raw.get("qc_focus")),
        example_good_lines=_as_list(raw.get("example_good_lines")),
        example_bad_lines=_as_list(raw.get("example_bad_lines")),
    )
