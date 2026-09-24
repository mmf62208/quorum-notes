"""Parse pasted roster lines. Names are not applied to present or roll here."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass

from .signin import normalize_name

# Longest civic / SAL / Roberts titles first so prefix/suffix match is greedy.
KNOWN_TITLES: tuple[str, ...] = (
    "Senior Vice Commander",
    "Junior Vice Commander",
    "First Vice Commander",
    "Second Vice Commander",
    "1st Vice Commander",
    "2nd Vice Commander",
    "Adjutant/Quartermaster",
    "Sergeant-at-Arms",
    "Sergeant at Arms",
    "Sgt-at-Arms",
    "Sgt at Arms",
    "Vice Commander",
    "Vice President",
    "Finance Officer",
    "Service Officer",
    "Membership Officer",
    "Judge Advocate",
    "First Vice",
    "Second Vice",
    "Senior Vice",
    "Junior Vice",
    "Quartermaster",
    "Commander",
    "Adjutant",
    "Chaplain",
    "Historian",
    "Treasurer",
    "Secretary",
    "President",
    "Chairperson",
    "Chairman",
    "Chair",
    "Trustee",
    "Finance",
    "Membership",
    "Advocate",
    "Surgeon",
)

HEADER_FIELDS = frozenset(
    {"name", "names", "title", "titles", "office", "officer", "role", "position"}
)
NAME_HEADER = frozenset({"name", "names"})
TITLE_HEADER = frozenset({"title", "titles", "office", "officer", "role", "position"})

_STOP = frozenset(
    {
        "yes",
        "no",
        "none",
        "n/a",
        "na",
        "present",
        "absent",
        "roster",
        "officers",
        "officer",
        "members",
        "member",
        "phone",
        "email",
        "notes",
        "total",
        "count",
        "ok",
        "true",
        "false",
    }
)
_TITLEISH = re.compile(
    r"\b(commander|adjutant|chaplain|officer|chair|chairman|chairperson|"
    r"secretary|treasurer|president|quartermaster|historian|advocate|"
    r"trustee|sergeant|sgt|surgeon|membership|finance|vice)\b",
    re.I,
)
_PHONE = re.compile(r"^\+?[\d().\s-]{7,}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL = re.compile(r"^https?://", re.I)
_LETTERS = re.compile(r"[A-Za-z]")
_TITLE_ALT = "|".join(re.escape(t) for t in sorted(KNOWN_TITLES, key=len, reverse=True))
_TITLE_PREFIX = re.compile(rf"^(?:the\s+)?({_TITLE_ALT})\b", re.I)
_TITLE_SUFFIX = re.compile(rf"\b({_TITLE_ALT})$", re.I)
_CANON_TITLE = {t.casefold(): t for t in KNOWN_TITLES}


@dataclass(frozen=True)
class RosterEntry:
    name: str
    title: str = ""
    raw: str = ""


def parse_roster(text: str) -> dict[str, list]:
    """Turn pasted text into confirmable entries. Skips garbage; invents nobody."""
    entries: list[RosterEntry] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    header: tuple[str, ...] | None = None

    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if header is None and _is_header_line(line):
            header = _header_order(line)
            continue
        parsed = _parse_line(line, header)
        if parsed is None:
            skipped.append({"line": line, "reason": "skipped"})
            continue
        key = normalize_name(parsed.name)
        if not key or key in seen:
            if key in seen:
                skipped.append({"line": line, "reason": "duplicate"})
            else:
                skipped.append({"line": line, "reason": "skipped"})
            continue
        seen.add(key)
        entries.append(parsed)

    return {
        "entries": [asdict(e) for e in entries],
        "skipped": skipped,
        "names": [e.name for e in entries],
    }


def _is_header_line(line: str) -> bool:
    fields = [f.casefold() for f in _split_fields(line) if f]
    if len(fields) < 2:
        return False
    return all(f in HEADER_FIELDS for f in fields)


def _header_order(line: str) -> tuple[str, ...]:
    fields = [f.casefold() for f in _split_fields(line) if f]
    roles: list[str] = []
    for field in fields:
        if field in NAME_HEADER:
            roles.append("name")
        elif field in TITLE_HEADER:
            roles.append("title")
        else:
            roles.append("other")
    return tuple(roles)


def _split_fields(line: str) -> list[str]:
    delimiter = "\t" if "\t" in line else "," if "," in line else ""
    if not delimiter:
        return [line.strip()]
    row = next(csv.reader(io.StringIO(line), delimiter=delimiter), [])
    return [" ".join((cell or "").split()) for cell in row]


def _parse_line(line: str, header: tuple[str, ...] | None) -> RosterEntry | None:
    fields = _split_fields(line)
    if header and len(fields) >= 2:
        mapped = _from_header_fields(fields, header, line)
        if mapped:
            return mapped
    if len(fields) >= 2:
        mapped = _from_two_fields(fields[0], fields[1], line)
        if mapped:
            return mapped
    pair = _split_title_name(line)
    if pair:
        title, name = pair
        if _plausible_name(name):
            return RosterEntry(name=_tidy_name(name), title=_tidy_title(title), raw=line)
        return None
    titled = _known_title_affix(line)
    if titled:
        return titled
    if _plausible_name(line) and "," not in line and "\t" not in line:
        return RosterEntry(name=_tidy_name(line), title="", raw=line)
    return None


def _from_header_fields(fields: list[str], header: tuple[str, ...], raw: str) -> RosterEntry | None:
    name = ""
    title = ""
    for role, value in zip(header, fields):
        if role == "name" and not name:
            name = value
        elif role == "title" and not title:
            title = value
    if not name and len(fields) >= 2:
        return _from_two_fields(fields[0], fields[1], raw)
    if _plausible_name(name):
        return RosterEntry(name=_tidy_name(name), title=_tidy_title(title), raw=raw)
    return None


def _from_two_fields(left: str, right: str, raw: str) -> RosterEntry | None:
    left_title = _known_title(left)
    right_title = _known_title(right)
    if left_title and _plausible_name(right):
        return RosterEntry(name=_tidy_name(right), title=left_title, raw=raw)
    if right_title and _plausible_name(left):
        return RosterEntry(name=_tidy_name(left), title=right_title, raw=raw)
    if _titleish(right) and _plausible_name(left):
        return RosterEntry(name=_tidy_name(left), title=_tidy_title(right), raw=raw)
    if _titleish(left) and _plausible_name(right):
        return RosterEntry(name=_tidy_name(right), title=_tidy_title(left), raw=raw)
    if _single_token(left) and _single_token(right) and _plausible_name(left) and _plausible_name(right):
        return RosterEntry(name=_tidy_name(f"{right} {left}"), title="", raw=raw)
    if _plausible_name(left):
        return RosterEntry(name=_tidy_name(left), title=_tidy_title(right), raw=raw)
    return None


def _split_title_name(line: str) -> tuple[str, str] | None:
    for sep in (":", " - ", " – ", " — ", " -"):
        if sep in line:
            left, right = [part.strip() for part in line.split(sep, 1)]
            if left and right:
                return left, right
    return None


def _known_title_affix(line: str) -> RosterEntry | None:
    prefix = _TITLE_PREFIX.match(line.strip())
    if prefix:
        rest = line.strip()[prefix.end() :].strip(" \t-–—:")
        if _plausible_name(rest):
            return RosterEntry(name=_tidy_name(rest), title=_canonical_title(prefix.group(1)), raw=line)
    suffix = _TITLE_SUFFIX.search(line.strip())
    if suffix and suffix.start() > 0:
        rest = line.strip()[: suffix.start()].strip(" \t-–—:,")
        if _plausible_name(rest):
            return RosterEntry(name=_tidy_name(rest), title=_canonical_title(suffix.group(1)), raw=line)
    return None


def _known_title(value: str) -> str:
    compact = " ".join((value or "").split())
    if not compact:
        return ""
    folded = compact.casefold()
    if folded.startswith("the "):
        folded = folded[4:]
    return _CANON_TITLE.get(folded, "")


def _canonical_title(value: str) -> str:
    return _known_title(value) or _tidy_title(value)


def _titleish(value: str) -> bool:
    return bool(_known_title(value) or _TITLEISH.search(value or ""))


def _single_token(value: str) -> bool:
    return len((value or "").split()) == 1


def _tidy_name(value: str) -> str:
    return " ".join((value or "").split()).strip(" ,;|-")


def _tidy_title(value: str) -> str:
    text = " ".join((value or "").split()).strip(" ,;|")
    return _known_title(text) or text


def _plausible_name(value: str) -> bool:
    name = _tidy_name(value)
    if len(name) < 2 or not _LETTERS.search(name):
        return False
    if _PHONE.match(name) or _EMAIL.match(name) or _URL.match(name):
        return False
    if name.casefold() in _STOP:
        return False
    if _known_title(name):
        return False
    if re.fullmatch(r"[-*_.=]{2,}", name):
        return False
    if name.isdigit():
        return False
    if name[:1] in "/\\@#":
        return False
    if "://" in name or name.casefold().startswith("www."):
        return False
    return True
