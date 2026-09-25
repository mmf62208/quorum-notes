"""House-style names: first name when unique, Mike F. / Mike G. when not."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .signin import normalize_name


def clean_name(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _tokens(name: str) -> list[str]:
    return [tok for tok in clean_name(name).replace(",", " ").split() if tok]


def _core_tokens(name: str) -> list[str]:
    return [tok for tok in _tokens(name) if not (tok.startswith("(") and tok.endswith(")"))]


def first_name(name: str) -> str:
    core = _core_tokens(name)
    return core[0] if core else clean_name(name)


def last_name(name: str) -> str:
    core = _core_tokens(name)
    if len(core) < 2:
        return ""
    return core[-1]


def last_initial(name: str) -> str:
    last = last_name(name)
    if not last:
        return ""
    letter = last[0]
    return letter.upper() if letter.isalpha() else letter


@dataclass(frozen=True)
class NameStyle:
    people: tuple[str, ...]
    _by_norm: dict[str, str]
    _first_groups: dict[str, list[str]]
    _first_initial_groups: dict[tuple[str, str], list[str]]

    def canonical(self, raw: str) -> str:
        name = clean_name(raw)
        if not name:
            return ""
        key = normalize_name(name)
        if key in self._by_norm:
            return self._by_norm[key]
        first = first_name(name).casefold()
        matches = self._first_groups.get(first) or []
        if len(matches) == 1:
            return matches[0]
        return name

    def spoken(self, raw: str) -> str:
        """Body and motion form: first name, or First + initial, or first + last."""
        full = self.canonical(raw)
        if not full:
            return ""
        first = first_name(full)
        group = self._first_groups.get(first.casefold()) or [full]
        if len(group) <= 1:
            return first
        initial = last_initial(full)
        keyed = self._first_initial_groups.get((first.casefold(), initial.casefold())) or [full]
        if initial and len(keyed) == 1:
            return f"{first} {initial}."
        last = last_name(full)
        if last:
            return f"{first} {last}"
        return full

    def roll(self, raw: str) -> str:
        """Full name, with (Mike F.) cue when first names collide."""
        full = self.canonical(raw) or clean_name(raw)
        if not full:
            return ""
        first = first_name(full)
        group = self._first_groups.get(first.casefold()) or [full]
        if len(group) <= 1:
            return full
        cue = self.spoken(full)
        if cue and cue not in {full, first}:
            return f"{full} ({cue})"
        return full


def style_for_names(names: Iterable[Any]) -> NameStyle:
    people: list[str] = []
    by_norm: dict[str, str] = {}
    for raw in names or []:
        name = clean_name(raw)
        if not name:
            continue
        key = normalize_name(name)
        if key in by_norm:
            continue
        by_norm[key] = name
        people.append(name)
    first_groups: dict[str, list[str]] = defaultdict(list)
    first_initial_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name in people:
        first = first_name(name).casefold()
        first_groups[first].append(name)
        first_initial_groups[(first, last_initial(name).casefold())].append(name)
    return NameStyle(
        people=tuple(people),
        _by_norm=by_norm,
        _first_groups=dict(first_groups),
        _first_initial_groups=dict(first_initial_groups),
    )


def names_from_meeting(meeting: Any, extra: Iterable[Any] | None = None) -> list[str]:
    """Officer memory (titles / extra) plus the meeting roster and people in the room."""
    names: list[str] = []
    for seq in (
        getattr(meeting, "roster", None) or [],
        getattr(meeting, "present", None) or [],
        getattr(meeting, "late", None) or [],
        getattr(meeting, "guests", None) or [],
        list(getattr(meeting, "roster_titles", None) or {}),
        extra or [],
    ):
        names.extend(seq)
    for motion in getattr(meeting, "new_business", None) or []:
        names.append(getattr(motion, "mover", "") or "")
        names.append(getattr(motion, "seconder", "") or "")
    for report in getattr(meeting, "reports", None) or []:
        names.append(getattr(report, "presenter", "") or "")
    names.append(getattr(meeting, "submitted_by", "") or "")
    return names
