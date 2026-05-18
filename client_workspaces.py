from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from config import CLIENT_WORKSPACES_DIR


@dataclass
class ClientWorkspace:
    client_id: str
    display_name: str
    tone_profile: str = "friction_first"
    default_campaign_context: str = ""
    default_research_region: str = "us"
    default_export_preset: str = "generic"
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


def slugify_client_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "client"


def workspace_path(client_id: str) -> Path:
    return CLIENT_WORKSPACES_DIR / slugify_client_name(client_id) / "client_profile.json"


def list_client_workspaces() -> list[ClientWorkspace]:
    if not CLIENT_WORKSPACES_DIR.exists():
        return []
    workspaces: list[ClientWorkspace] = []
    for path in sorted(CLIENT_WORKSPACES_DIR.glob("*/client_profile.json")):
        workspace = load_client_workspace(path.parent.name)
        if workspace:
            workspaces.append(workspace)
    return workspaces


def load_client_workspace(client_id: str) -> ClientWorkspace | None:
    path = workspace_path(client_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return ClientWorkspace(
        client_id=str(data.get("client_id") or path.parent.name),
        display_name=str(data.get("display_name") or data.get("client_id") or path.parent.name),
        tone_profile=str(data.get("tone_profile") or "friction_first"),
        default_campaign_context=str(data.get("default_campaign_context") or ""),
        default_research_region=str(data.get("default_research_region") or "us"),
        default_export_preset=str(data.get("default_export_preset") or "generic"),
        notes=str(data.get("notes") or ""),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


def save_client_workspace(workspace: ClientWorkspace) -> Path:
    now = datetime.now().isoformat(timespec="seconds")
    client_id = slugify_client_name(workspace.client_id or workspace.display_name)
    existing = load_client_workspace(client_id)
    workspace.client_id = client_id
    workspace.created_at = workspace.created_at or (existing.created_at if existing else now)
    workspace.updated_at = now
    path = workspace_path(client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(workspace), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
