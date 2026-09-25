"""First-run settings. Retention and org live with the vault."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import vault_dir
from .quorum_rule import normalize_quorum_rule

DEFAULTS: dict[str, Any] = {
    "setup_complete": False,
    "organization": "",
    "submitted_by": "",
    "submitted_office": "Adjutant",
    "template": "sal",
    "roberts": True,
    "retention": "until_approved",
    "default_location": "",
    "called_to_order_by": "Commander",
    "roster": [
        "Member A",
        "Member B",
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
    if "quorum_rule" in data:
        data["quorum_rule"] = normalize_quorum_rule(data.get("quorum_rule")).to_dict()
    if "roster_titles" in data:
        data["roster_titles"] = _clean_roster_titles(data.get("roster_titles"))
    return data


def _clean_roster_titles(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        name = " ".join(str(key or "").split()).strip()
        title = " ".join(str(value or "").split()).strip()
        if name and title:
            cleaned[name] = title
    return cleaned


def _merge_roster_titles(existing: Any, incoming: Any, roster_names: Any) -> dict[str, str]:
    cleaned = _clean_roster_titles(incoming)
    if cleaned:
        return cleaned
    names = {" ".join(str(name or "").split()).casefold() for name in (roster_names or [])}
    kept: dict[str, str] = {}
    for name, title in (_clean_roster_titles(existing) or {}).items():
        if name.casefold() in names:
            kept[name] = title
    return kept


def save_settings(update: dict[str, Any]) -> dict[str, Any]:
    data = load_settings()
    incoming = dict(update or {})
    if "quorum_rule" in incoming:
        incoming["quorum_rule"] = normalize_quorum_rule(incoming.get("quorum_rule")).to_dict()
    if "roster_titles" in incoming:
        incoming["roster_titles"] = _merge_roster_titles(
            data.get("roster_titles"),
            incoming.get("roster_titles"),
            incoming.get("roster") or data.get("roster") or [],
        )
    data.update(incoming)
    if data.get("retention") not in RETENTION_CHOICES:
        raise ValueError("retention must be until_approved, 7d, 14d, or keep")
    vault_dir().mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data
