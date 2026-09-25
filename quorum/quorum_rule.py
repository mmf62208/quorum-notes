"""Org quorum rule: storage shape, pure evaluation, banner + minutes copy.

Local only. Unmet quorum never blocks a meeting.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from . import roster
from .signin import normalize_name

MODES = ("structured", "text", "none")

SAL_POST_484_NOTES = "SAL Post 484: Commander or presiding 1st/2nd Vice + at least 3 other officers"
SAL_POST_484_PRESIDING = ("Commander", "1st Vice Commander", "2nd Vice Commander")

QUORUM_MINUTES_LINE_RE = re.compile(
    r"^[ \t]*(?:Quorum: (?:Met|Not met)\b.*|Quorum rule: .*\(Checked manually\.\))[ \t]*$",
    re.M,
)
PREVIOUS_MINUTES_MARK = "**Approval of Previous Minutes:**"


def _opt_int(value: Any, *, zero_ok: bool = True) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if not zero_ok and number <= 0:
        return None
    return number


def _clean_titles(values: Any) -> tuple[str, ...]:
    titles: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = " ".join(str(raw or "").split()).strip()
        if not text:
            continue
        key = roster.normalize_title(text) or text.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(roster.display_title(text) or text)
    return tuple(titles)


@dataclass(frozen=True)
class QuorumRule:
    mode: str = "none"
    presiding_any_of: tuple[str, ...] = ()
    min_other_officers: int | None = None
    min_members_total: int | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "presiding_any_of": list(self.presiding_any_of),
            "min_other_officers": self.min_other_officers,
            "min_members_total": self.min_members_total,
            "notes": self.notes,
        }


SAL_POST_484_RULE = QuorumRule(
    mode="structured",
    presiding_any_of=SAL_POST_484_PRESIDING,
    min_other_officers=3,
    min_members_total=None,
    notes=SAL_POST_484_NOTES,
)


def normalize_quorum_rule(raw: Any) -> QuorumRule:
    """Missing / invalid / none → mode none. Never raises on old vault data."""
    if not isinstance(raw, dict):
        return QuorumRule()
    mode = str(raw.get("mode") or "none").strip().casefold()
    if mode not in MODES:
        mode = "none"
    notes = str(raw.get("notes") or "").strip()
    if mode == "none":
        return QuorumRule(mode="none", notes=notes)
    if mode == "text":
        return QuorumRule(mode="text", notes=notes)
    min_officers = _opt_int(raw.get("min_other_officers"), zero_ok=True)
    min_total = _opt_int(raw.get("min_members_total"), zero_ok=False)
    return QuorumRule(
        mode="structured",
        presiding_any_of=_clean_titles(raw.get("presiding_any_of")),
        min_other_officers=min_officers,
        min_members_total=min_total,
        notes=notes,
    )


def is_officer_title(title: str) -> bool:
    text = " ".join((title or "").split()).strip()
    if not text:
        return False
    return text.casefold() != "member"


def _person_name(person: Any) -> str:
    if isinstance(person, dict):
        return " ".join(str(person.get("name") or "").split()).strip()
    return " ".join(str(getattr(person, "name", "") or "").split()).strip()


def _person_title(person: Any) -> str:
    if isinstance(person, dict):
        return " ".join(str(person.get("title") or "").split()).strip()
    return " ".join(str(getattr(person, "title", "") or "").split()).strip()


def present_people_from(names: Iterable[Any], titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    lookup = {normalize_name(key): value for key, value in (titles or {}).items() if key}
    people: list[dict[str, str]] = []
    for raw in names or []:
        if isinstance(raw, dict) or hasattr(raw, "name"):
            name = _person_name(raw)
            title = _person_title(raw) or lookup.get(normalize_name(name), "")
        else:
            name = " ".join(str(raw or "").split()).strip()
            title = lookup.get(normalize_name(name), "")
        if not name:
            continue
        people.append({"name": name, "title": title})
    return people


def _sal_presiding(titles: tuple[str, ...]) -> bool:
    keys = {roster.normalize_title(title) for title in titles}
    return keys == {roster.normalize_title(title) for title in SAL_POST_484_PRESIDING}


def format_presiding_need(titles: Iterable[str]) -> str:
    cleaned = _clean_titles(titles)
    if not cleaned:
        return ""
    if _sal_presiding(cleaned):
        return "Commander or 1st/2nd Vice"
    labels = [roster.display_title(title) for title in cleaned]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} or {labels[1]}"
    return f"{', '.join(labels[:-1])}, or {labels[-1]}"


def preview_rule(rule: QuorumRule | Any) -> str:
    normalized = rule if isinstance(rule, QuorumRule) else normalize_quorum_rule(rule)
    if normalized.mode == "none":
        return "No special quorum rule."
    if normalized.mode == "text":
        return normalized.notes or "Check quorum manually."
    if normalized.mode != "structured":
        raise ValueError(f"unknown quorum mode {normalized.mode!r}")
    if _sal_presiding(normalized.presiding_any_of) and normalized.min_other_officers == 3:
        return "Quorum = Commander or 1st/2nd Vice presiding, plus at least 3 other officers."
    bits: list[str] = []
    if normalized.presiding_any_of:
        bits.append(f"{format_presiding_need(normalized.presiding_any_of)} presiding")
    if normalized.min_other_officers:
        noun = "officer" if normalized.min_other_officers == 1 else "officers"
        bits.append(f"plus at least {normalized.min_other_officers} other {noun}")
    if normalized.min_members_total:
        noun = "member" if normalized.min_members_total == 1 else "members"
        bits.append(f"a total of at least {normalized.min_members_total} {noun} present")
    if not bits:
        return "No special quorum rule."
    if len(bits) == 1:
        return f"Quorum = {bits[0]}."
    return f"Quorum = {bits[0]}, {', '.join(bits[1:])}."


def rule_short(rule: QuorumRule) -> str:
    if _sal_presiding(rule.presiding_any_of) and rule.min_other_officers == 3:
        return "Commander or 1st/2nd Vice + 3 officers"
    bits: list[str] = []
    if rule.presiding_any_of:
        bits.append(format_presiding_need(rule.presiding_any_of))
    if rule.min_other_officers:
        noun = "officer" if rule.min_other_officers == 1 else "officers"
        bits.append(f"{rule.min_other_officers} {noun}")
    if rule.min_members_total:
        noun = "member" if rule.min_members_total == 1 else "members"
        bits.append(f"{rule.min_members_total} {noun}")
    return " + ".join(bits) if bits else "custom"


def _rule_note_lead(note: str) -> str:
    text = (note or "").strip()
    if text.endswith((".", "!", "?")):
        return f"Quorum rule: {text}"
    return f"Quorum rule: {text}."


def _more_officers(needed: int) -> str:
    return "1 more officer" if needed == 1 else f"{needed} more officers"


def _more_members(needed: int) -> str:
    return "1 more member" if needed == 1 else f"{needed} more members"


@dataclass(frozen=True)
class QuorumResult:
    status: str
    need: str = ""
    missing: tuple[str, ...] = ()
    presiding_title: str = ""
    other_officers: int = 0
    present_count: int = 0
    notes: str = ""
    banner_title: str = ""
    banner_detail: str = ""
    minutes_line: str = ""
    rule_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["missing"] = list(self.missing)
        return data


def evaluate_quorum(rule: Any, present_people: Iterable[Any]) -> QuorumResult | None:
    """Pure check. None means no rule / nothing to show."""
    normalized = rule if isinstance(rule, QuorumRule) else normalize_quorum_rule(rule)
    people = present_people_from(present_people)
    present_count = len(people)

    if normalized.mode == "none":
        return None
    if normalized.mode == "text":
        note = normalized.notes
        banner = (
            f"{_rule_note_lead(note)} Check quorum manually."
            if note
            else "Check quorum manually."
        )
        minutes = (
            f"{_rule_note_lead(note)} (Checked manually.)"
            if note
            else "Quorum rule: (Checked manually.)"
        )
        return QuorumResult(
            status="manual",
            notes=note,
            present_count=present_count,
            banner_title=banner,
            banner_detail="",
            minutes_line=minutes,
            rule_summary=note,
        )
    if normalized.mode != "structured":
        raise ValueError(f"unknown quorum mode {normalized.mode!r}")

    min_officers = normalized.min_other_officers or 0
    min_total = normalized.min_members_total

    presiding_person = None
    presiding_title = ""
    if not normalized.presiding_any_of:
        presiding_ok = True
    else:
        presiding_ok = False
        for wanted in normalized.presiding_any_of:
            for person in people:
                if roster.titles_match(_person_title(person), wanted):
                    presiding_ok = True
                    presiding_person = person
                    presiding_title = roster.display_title(_person_title(person) or wanted)
                    break
            if presiding_ok:
                break

    preside_key = normalize_name(_person_name(presiding_person)) if presiding_person else ""
    others = [
        person
        for person in people
        if is_officer_title(_person_title(person))
        and (not preside_key or normalize_name(_person_name(person)) != preside_key)
    ]

    officers_ok = len(others) >= min_officers
    total_ok = min_total is None or present_count >= min_total
    met = presiding_ok and officers_ok and total_ok
    summary = rule_short(normalized)

    missing: list[str] = []
    if not presiding_ok:
        missing.append(format_presiding_need(normalized.presiding_any_of))
    if not officers_ok:
        missing.append(_more_officers(min_officers - len(others)))
    if not total_ok and min_total is not None:
        missing.append(_more_members(min_total - present_count))
    need = " and ".join(missing)

    if met:
        if presiding_title:
            detail = f"{presiding_title} + {len(others)} other officers present (rule: {summary})"
            minutes = (
                f"Quorum: Met ({presiding_title} presiding; {len(others)} other officers present)."
            )
        elif min_total is not None and not normalized.presiding_any_of and not min_officers:
            detail = f"{present_count} members present (rule: {summary})"
            minutes = f"Quorum: Met ({present_count} members present)."
        else:
            detail = f"{len(others)} officers present (rule: {summary})"
            minutes = f"Quorum: Met ({len(others)} officers present)."
        return QuorumResult(
            status="met",
            presiding_title=presiding_title,
            other_officers=len(others),
            present_count=present_count,
            notes=normalized.notes,
            banner_title="Quorum met",
            banner_detail=detail,
            minutes_line=minutes,
            rule_summary=summary,
        )

    return QuorumResult(
        status="not_met",
        need=need,
        missing=tuple(missing),
        presiding_title=presiding_title,
        other_officers=len(others),
        present_count=present_count,
        notes=normalized.notes,
        banner_title=f"Not met: need {need}" if need else "Not met",
        banner_detail=f"rule: {summary}" if summary else "",
        minutes_line=f"Quorum: Not met (need {need})." if need else "Quorum: Not met.",
        rule_summary=summary,
    )


def upsert_quorum_minutes_line(text: str, line: str | None) -> str:
    """Put one generated quorum line after attendance; never duplicate."""
    body = QUORUM_MINUTES_LINE_RE.sub("", text or "")
    body = re.sub(r"\n{3,}", "\n\n", body)
    if not (line or "").strip():
        return body if body.endswith("\n") else body + "\n"
    block = line.strip() + "\n\n"
    idx = body.find(PREVIOUS_MINUTES_MARK)
    if idx == -1:
        return body.rstrip() + "\n\n" + block
    return body[:idx].rstrip() + "\n\n" + block + body[idx:]


def apply_result_to_meeting(meeting: Any, result: QuorumResult | None) -> Any:
    """Write the generated minutes line unless the adjutant hand-edited it."""
    if getattr(meeting, "org_quorum_line_edited", False):
        return meeting
    meeting.org_quorum_line = "" if result is None else result.minutes_line
    return meeting
