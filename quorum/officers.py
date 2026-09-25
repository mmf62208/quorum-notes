"""Remembered officers: role + name pairs per org. Local vault only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from . import roster
from .quorum_rule import is_officer_title
from .signin import normalize_name


@dataclass(frozen=True)
class Officer:
    role: str
    name: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "name": self.name}


def _clean_role(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    return roster.display_title(text) or text


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _role_key(role: str) -> str:
    return roster.normalize_title(role) or role.casefold()


def normalize_officers(raw: Any) -> list[Officer]:
    """Missing / invalid → []. Never raises on old vault data."""
    if not isinstance(raw, list):
        return []
    officers: list[Officer] = []
    seen: dict[str, int] = {}
    for item in raw:
        if isinstance(item, Officer):
            role, name = item.role, item.name
        elif isinstance(item, dict):
            role = _clean_role(item.get("role") or item.get("title") or item.get("office"))
            name = _clean_name(item.get("name"))
        else:
            continue
        role = _clean_role(role)
        name = _clean_name(name)
        if not role:
            continue
        key = _role_key(role)
        officer = Officer(role=role, name=name)
        if key in seen:
            officers[seen[key]] = officer
            continue
        seen[key] = len(officers)
        officers.append(officer)
    return officers


def officers_to_dicts(officers: Iterable[Officer | dict[str, str]]) -> list[dict[str, str]]:
    return [officer.to_dict() for officer in normalize_officers(list(officers or []))]


def officers_from_roster_titles(titles: Any) -> list[Officer]:
    """Seed role + name from A2 setup roster titles. Member / blank titles skipped."""
    if not isinstance(titles, dict):
        return []
    pairs: list[dict[str, str]] = []
    for raw_name, raw_title in titles.items():
        role = _clean_role(raw_title)
        name = _clean_name(raw_name)
        if not role or not name or not is_officer_title(role):
            continue
        pairs.append({"role": role, "name": name})
    return normalize_officers(pairs)


def resolve_officers(settings: dict[str, Any] | None) -> list[Officer]:
    """Use stored officers when the key exists (even if empty); else seed from roster titles."""
    data = settings if isinstance(settings, dict) else {}
    if "officers" in data:
        return normalize_officers(data.get("officers"))
    return officers_from_roster_titles(data.get("roster_titles"))


def titles_from_officers(officers: Iterable[Officer]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for officer in normalize_officers(list(officers or [])):
        if officer.name and officer.role:
            titles[officer.name] = officer.role
    return titles


def roles_from_officers(officers: Iterable[Officer]) -> list[str]:
    roles: list[str] = []
    seen: set[str] = set()
    for officer in normalize_officers(list(officers or [])):
        key = _role_key(officer.role)
        if key in seen:
            continue
        seen.add(key)
        roles.append(officer.role)
    return roles


def merge_officer_names(roster_names: Iterable[Any], officers: Iterable[Officer]) -> list[str]:
    """Add named officers to the roster. Vacated roles are skipped. Never marks present."""
    names = [" ".join(str(name or "").split()).strip() for name in (roster_names or [])]
    names = [name for name in names if name]
    keys = {normalize_name(name) for name in names}
    for officer in normalize_officers(list(officers or [])):
        if not officer.name:
            continue
        key = normalize_name(officer.name)
        if key in keys:
            continue
        names.append(officer.name)
        keys.add(key)
    return names


def apply_officer_titles(existing: Any, officers: Iterable[Officer]) -> dict[str, str]:
    """Remembered roles win over stale setup titles for the same office."""
    titles: dict[str, str] = {}
    if isinstance(existing, dict):
        managed = {_role_key(officer.role) for officer in normalize_officers(list(officers or []))}
        for raw_name, raw_title in existing.items():
            name = _clean_name(raw_name)
            title = _clean_role(raw_title)
            if not name or not title:
                continue
            if _role_key(title) in managed:
                continue
            titles[name] = title
    titles.update(titles_from_officers(officers))
    return titles


def swap_officer_name(officers: Iterable[Officer], role: str, name: str) -> list[Officer]:
    cleaned_role = _clean_role(role)
    if not cleaned_role:
        return normalize_officers(list(officers or []))
    wanted = _role_key(cleaned_role)
    updated = normalize_officers(list(officers or []))
    for index, officer in enumerate(updated):
        if _role_key(officer.role) == wanted:
            updated[index] = Officer(role=officer.role, name=_clean_name(name))
            return updated
    updated.append(Officer(role=cleaned_role, name=_clean_name(name)))
    return updated


def vacate_officer(officers: Iterable[Officer], role: str) -> list[Officer]:
    return swap_officer_name(officers, role, "")


def add_officer_role(officers: Iterable[Officer], role: str, name: str = "") -> list[Officer]:
    return swap_officer_name(officers, role, name)
