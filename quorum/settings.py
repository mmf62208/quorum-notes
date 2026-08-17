"""First-run settings. Retention and org live with the vault."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import vault_dir

DEFAULTS: dict[str, Any] = {
    "setup_complete": False,
    "organization": "SAL Post 484 Squadron",
    "submitted_by": "Mike Featherstone",
    "submitted_office": "Adjutant, SAL Post 484",
    "template": "sal",
    "roberts": True,
    "retention": "until_approved",
    "default_location": "Post home",
    "called_to_order_by": "Commander",
    "roster": [
        "Jeff Shumaker",
        "Herm Clear",
        "Gene Newell",
        "Mike Featherstone",
        "Ted Ruser",
        "Kirk Dewey",
        "Paul Nichols",
        "William Wood",
        "Mike Gerlofs",
        "Randy Robbins",
        "William Fayling",
    ],
}

RETENTION_CHOICES = ("until_approved", "7d", "14d", "keep")


def settings_path() -> Path:
    return vault_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data = dict(DEFAULTS)
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update(saved)
        except json.JSONDecodeError:
            pass
    if data.get("retention") not in RETENTION_CHOICES:
        data["retention"] = "until_approved"
    return data


def save_settings(update: dict[str, Any]) -> dict[str, Any]:
    data = load_settings()
    data.update(update or {})
    if data.get("retention") not in RETENTION_CHOICES:
        raise ValueError("retention must be until_approved, 7d, 14d, or keep")
    vault_dir().mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data
