"""Formal minutes helpers: roll call / quorum, motions, SAL-style render."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .name_style import NameStyle, names_from_meeting, style_for_names
from .quorum_rule import is_officer_title
from .roster import display_title
from .signin import normalize_name

SAL_POST_484_CLOSING = "For God and Country"


@dataclass
class Motion:
    text: str
    mover: str = ""
    seconder: str = ""
    yeas: int = 0
    nays: int = 0
    abstain: int = 0
    result: str = "pending"  # pending | carried | failed | withdrawn | tabled

    def decide(self) -> str:
        if self.result in {"withdrawn", "tabled"}:
            return self.result
        if not self.seconder:
            self.result = "failed"
            return self.result
        self.result = "carried" if self.yeas > self.nays else "failed"
        return self.result


def apply_motion_result(motion: Motion, result: str, roberts: bool = True) -> Motion:
    """Mark a motion result. With Robert’s Rules on, carried requires a second."""
    if result == "carried" and roberts and not (motion.seconder or "").strip():
        raise ValueError("Need a second before it can carry")
    motion.result = result
    return motion


def enforce_motion_rules(meeting: Meeting) -> Meeting:
    """Refuse to persist a carried motion that lacks a second when RR is on."""
    if not meeting.roberts:
        return meeting
    for motion in meeting.new_business:
        if motion.result == "carried" and not (motion.seconder or "").strip():
            raise ValueError("Need a second before it can carry")
    return meeting


@dataclass
class Report:
    title: str
    presenter: str = ""
    body: str = ""


@dataclass
class SpeakerMark:
    seconds: float
    name: str


@dataclass
class Takeaway:
    text: str
    owner: str = ""


@dataclass
class Photo:
    name: str
    kind: str = "document"  # document | sign_in
    data_url: str = ""


DOC_LABELS = (
    "finance",
    "agenda",
    "handout",
    "bylaws",
    "standing_rules",
    "prior_minutes",
    "other",
)

NAME_STYLE_CHOICES = ("first", "full")
MOTION_PHRASING_CHOICES = ("moved_seconded", "motion_by")
SIGNATURE_SHAPE_CHOICES = ("respectfully", "submitted_by_line")

DEFAULT_HEADING_ORDER = (
    "called_to_order",
    "opening",
    "roll_call",
    "officers",
    "previous_minutes",
    "reports",
    "old_business",
    "new_business",
    "announcements",
    "adjournment",
    "takeaways",
    "speaker_marks",
    "signature",
)

HEADING_LABELS = {
    "called_to_order": "Meeting Called to Order",
    "opening": "Opening Ceremonies",
    "roll_call": "Roll Call / Quorum",
    "officers": "Officers",
    "previous_minutes": "Approval of Previous Minutes",
    "reports": "Reports",
    "old_business": "Old Business",
    "new_business": "New Business",
    "announcements": "Announcements / Good of the Order",
    "adjournment": "Adjournment",
    "takeaways": "Takeaways / assignments",
    "speaker_marks": "Speaker marks",
    "signature": "Respectfully submitted",
}


def normalize_doc_label(label: str) -> str:
    key = (label or "other").strip().casefold().replace(" ", "_").replace("-", "_")
    if key in {"bylaw", "by_laws"}:
        key = "bylaws"
    if key in {
        "minutes",
        "previous_minutes",
        "last_minutes",
        "prior_minute",
        "accepted_minutes",
        "last_accepted_minutes",
    }:
        key = "prior_minutes"
    return key if key in DOC_LABELS else "other"


def normalize_name_style(raw: Any) -> str:
    key = str(raw or "").strip().casefold().replace("-", "_")
    return key if key in NAME_STYLE_CHOICES else "first"


def normalize_motion_phrasing(raw: Any) -> str:
    key = str(raw or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if key in {"motion_by", "motionby", "by_x_seconded_by_y"}:
        return "motion_by"
    if key in MOTION_PHRASING_CHOICES:
        return key
    return "moved_seconded"


def normalize_signature_shape(raw: Any) -> str:
    key = str(raw or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if key in {"submitted_by", "submitted_by_line", "submittedby"}:
        return "submitted_by_line"
    if key in SIGNATURE_SHAPE_CHOICES:
        return key
    return "respectfully"


_HEADING_ALIASES = {
    "called_to_order": "called_to_order",
    "meeting_called_to_order": "called_to_order",
    "opening": "opening",
    "opening_ceremonies": "opening",
    "roll_call": "roll_call",
    "roll_call_quorum": "roll_call",
    "officers": "officers",
    "previous_minutes": "previous_minutes",
    "approval_of_previous_minutes": "previous_minutes",
    "reports": "reports",
    "old_business": "old_business",
    "unfinished_business": "old_business",
    "new_business": "new_business",
    "announcements": "announcements",
    "good_of_the_order": "announcements",
    "adjournment": "adjournment",
    "adjourn": "adjournment",
    "takeaways": "takeaways",
    "speaker_marks": "speaker_marks",
    "signature": "signature",
}


def parse_heading_keys(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.replace("|", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        values = [str(part or "").strip() for part in raw]
    seen: set[str] = set()
    order: list[str] = []
    for item in values:
        key = item.casefold().replace(" ", "_").replace("-", "_")
        mapped = _HEADING_ALIASES.get(key)
        if not mapped or mapped in seen:
            continue
        seen.add(mapped)
        order.append(mapped)
    return order


def normalize_heading_order(raw: Any) -> list[str]:
    detected = parse_heading_keys(raw)
    if not detected:
        return list(DEFAULT_HEADING_ORDER)
    detected_set = set(detected)
    order: list[str] = []
    det_iter = iter(detected)
    nxt = next(det_iter, None)
    for key in DEFAULT_HEADING_ORDER:
        if key in detected_set:
            if nxt is not None:
                order.append(nxt)
                nxt = next(det_iter, None)
        else:
            order.append(key)
    while nxt is not None:
        if nxt not in order:
            order.append(nxt)
        nxt = next(det_iter, None)
    return order


def heading_order_label(order: list[str] | tuple[str, ...]) -> str:
    return " → ".join(HEADING_LABELS.get(key, key) for key in order if key in HEADING_LABELS)


@dataclass(frozen=True)
class MinutesStyle:
    name_style: str = "first"
    motion_phrasing: str = "moved_seconded"
    heading_order: tuple[str, ...] = DEFAULT_HEADING_ORDER
    signature_shape: str = "respectfully"
    closing: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "minutes_name_style": self.name_style,
            "minutes_motion_phrasing": self.motion_phrasing,
            "minutes_heading_order": list(self.heading_order),
            "minutes_signature_shape": self.signature_shape,
            "minutes_closing": self.closing,
        }


def minutes_style_from(raw: Any, closing: str = "") -> MinutesStyle:
    data = raw if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        data = {
            "minutes_name_style": getattr(raw, "minutes_name_style", ""),
            "minutes_motion_phrasing": getattr(raw, "minutes_motion_phrasing", ""),
            "minutes_heading_order": getattr(raw, "minutes_heading_order", None),
            "minutes_signature_shape": getattr(raw, "minutes_signature_shape", ""),
            "minutes_closing": getattr(raw, "minutes_closing", "") or getattr(raw, "closing", ""),
        }
    close = " ".join(str(closing or data.get("minutes_closing") or data.get("closing") or "").split()).strip()
    return MinutesStyle(
        name_style=normalize_name_style(data.get("minutes_name_style")),
        motion_phrasing=normalize_motion_phrasing(data.get("minutes_motion_phrasing")),
        heading_order=tuple(normalize_heading_order(data.get("minutes_heading_order"))),
        signature_shape=normalize_signature_shape(data.get("minutes_signature_shape")),
        closing=close,
    )


@dataclass
class MeetingDocument:
    """Vault file attached to a meeting. Bytes live on disk, not in this record."""

    label: str = "other"
    filename: str = ""
    bytes: int = 0
    time: str = ""


def _as_document(item: Any) -> MeetingDocument:
    if isinstance(item, MeetingDocument):
        return item
    if not isinstance(item, dict):
        raise TypeError("invalid document")
    known = {f.name for f in MeetingDocument.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return MeetingDocument(**{k: v for k, v in item.items() if k in known})


@dataclass
class Meeting:
    id: str
    title: str = "Regular Meeting"
    organization: str = ""
    date: str = ""
    location: str = ""
    called_to_order_by: str = ""
    opening: list[str] = field(default_factory=list)
    roster: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    quorum_rule: str = "majority"  # majority | fixed
    quorum_fixed: int = 0
    previous_minutes: str = "pending"  # pending | approved | approved_as_corrected | not_read
    previous_minutes_note: str = ""
    reports: list[Report] = field(default_factory=list)
    old_business: list[str] = field(default_factory=list)
    new_business: list[Motion] = field(default_factory=list)
    announcements: list[str] = field(default_factory=list)
    adjournment: str = ""
    submitted_by: str = ""
    submitted_office: str = "Adjutant"
    closing: str = ""
    minutes_closing: str = ""
    notes: str = ""
    late: list[str] = field(default_factory=list)
    guests: list[str] = field(default_factory=list)
    speaker_marks: list[SpeakerMark] = field(default_factory=list)
    takeaways: list[Takeaway] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)
    documents: list[MeetingDocument] = field(default_factory=list)
    file_stem: str = ""
    roberts: bool = True
    minutes_approved: bool = False
    agenda_index: int = 0
    has_audio: bool = False
    has_transcript: bool = False
    created_at: str = ""
    updated_at: str = ""
    roster_titles: dict[str, str] = field(default_factory=dict)
    org_quorum_line: str = ""
    org_quorum_line_edited: bool = False
    minutes_name_style: str = ""
    minutes_motion_phrasing: str = ""
    minutes_heading_order: list[str] = field(default_factory=list)
    minutes_signature_shape: str = ""

    def quorum_required(self) -> int:
        if self.quorum_rule == "fixed":
            return max(int(self.quorum_fixed), 0)
        n = len(self.roster)
        return (n // 2) + 1 if n else 0

    def quorum_present(self) -> bool:
        required = self.quorum_required()
        if required == 0:
            return bool(self.present)
        return len(self.present) >= required

    def roll_call(self) -> dict[str, Any]:
        present = [n for n in self.present if n]
        late = [n for n in self.late if n]
        guests = [n for n in self.guests if n]
        marked = set(present) | set(late)
        absent = [n for n in self.roster if n and n not in marked]
        extra = [n for n in present if n not in self.roster]
        return {
            "roster_count": len(self.roster),
            "present_count": len(present),
            "late": late,
            "guests": guests,
            "absent_count": len(absent),
            "guests_or_unlisted": extra,
            "absent": absent,
            "required": self.quorum_required(),
            "quorum": self.quorum_present(),
            "rule": self.quorum_rule,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Meeting":
        payload = dict(data)
        payload["reports"] = [Report(**r) if isinstance(r, dict) else r for r in payload.get("reports", [])]
        payload["new_business"] = [
            Motion(**m) if isinstance(m, dict) else m for m in payload.get("new_business", [])
        ]
        payload["speaker_marks"] = [
            SpeakerMark(**s) if isinstance(s, dict) else s for s in payload.get("speaker_marks", [])
        ]
        payload["takeaways"] = [
            Takeaway(**t) if isinstance(t, dict) else t for t in payload.get("takeaways", [])
        ]
        payload["photos"] = [Photo(**p) if isinstance(p, dict) else p for p in payload.get("photos", [])]
        payload["documents"] = [_as_document(d) for d in payload.get("documents", [])]
        titles = payload.get("roster_titles") or {}
        payload["roster_titles"] = dict(titles) if isinstance(titles, dict) else {}
        payload["minutes_heading_order"] = parse_heading_keys(payload.get("minutes_heading_order"))
        payload["minutes_name_style"] = str(payload.get("minutes_name_style") or "")
        payload["minutes_motion_phrasing"] = str(payload.get("minutes_motion_phrasing") or "")
        payload["minutes_signature_shape"] = str(payload.get("minutes_signature_shape") or "")
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})


def _bullet(text: str) -> str:
    item = " ".join((text or "").split()).strip()
    if item.startswith(("* ", "- ")):
        item = item[2:].strip()
    return f"* {item}"


def _looks_like_list_line(text: str) -> bool:
    stripped = (text or "").strip()
    if stripped.startswith(("* ", "- ", "*\t", "-\t")):
        return True
    if stripped[:1].isdigit() and ". " in stripped[:4]:
        return True
    return False


def _is_listish(text: str) -> bool:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) <= 1:
        return False
    return all(_looks_like_list_line(ln) for ln in lines)


def _run_in(header: str, body: str) -> list[str]:
    """Bold header on the same line as a single-block body; list bodies stay stacked."""
    text = (body or "").strip()
    if not text:
        return [f"**{header}:**"]
    if "\n" in text or _is_listish(text):
        out = [f"**{header}:**"]
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            out.append(_bullet(stripped) if _looks_like_list_line(stripped) else stripped)
        return out
    return [f"**{header}:** {text}"]


def _title_for(meeting: Meeting, name: str) -> str:
    titles = meeting.roster_titles or {}
    if name in titles:
        return display_title(titles[name]) or titles[name]
    key = normalize_name(name)
    for raw, title in titles.items():
        if normalize_name(raw) == key:
            return display_title(title) or title
    return ""


def _officer_entries(meeting: Meeting) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in meeting.roster or []:
        title = _title_for(meeting, name)
        if not name or not title or not is_officer_title(title):
            continue
        seen.add(normalize_name(name))
        entries.append((name, title))
    for name, raw_title in (meeting.roster_titles or {}).items():
        title = display_title(raw_title) or raw_title
        if not name or not title or not is_officer_title(title):
            continue
        key = normalize_name(name)
        if key in seen:
            continue
        seen.add(key)
        entries.append((name, title))
    return entries


def _attendance_status(meeting: Meeting, name: str) -> str:
    key = normalize_name(name)
    if key in {normalize_name(n) for n in (meeting.present or []) if n}:
        return "present"
    if key in {normalize_name(n) for n in (meeting.late or []) if n}:
        return "late"
    return "absent"


def _other_present(meeting: Meeting, officer_keys: set[str]) -> list[str]:
    others: list[str] = []
    seen: set[str] = set()
    for name in list(meeting.present or []) + list(meeting.late or []) + list(meeting.guests or []):
        if not name:
            continue
        key = normalize_name(name)
        if key in officer_keys or key in seen:
            continue
        seen.add(key)
        others.append(name)
    return others


def _motion_clause(text: str) -> str:
    cleaned = (text or "").strip().rstrip(".")
    if not cleaned:
        return "moved"
    low = cleaned.casefold()
    if low.startswith(("to ", "that ")):
        return f"moved {cleaned}"
    return f"moved to {cleaned}"


def _spoken_name(style: NameStyle, name: str, name_mode: str) -> str:
    if normalize_name_style(name_mode) == "full":
        return style.canonical(name) or " ".join((name or "").split()).strip()
    return style.spoken(name)


def _format_motion(
    motion: Motion,
    style: NameStyle,
    phrasing: str = "moved_seconded",
    name_mode: str = "first",
) -> str:
    who = _spoken_name(style, motion.mover, name_mode) or "A member"
    second = ""
    if (motion.seconder or "").strip():
        second = _spoken_name(style, motion.seconder, name_mode)
    if normalize_motion_phrasing(phrasing) == "motion_by":
        clause = _motion_clause(motion.text)
        body = clause[6:] if clause.startswith("moved ") else ""
        if second:
            line = f"Motion by {who}, seconded by {second}"
        else:
            line = f"Motion by {who}"
        if body:
            line += f", {body}"
        line += "."
    else:
        line = f"{who} {_motion_clause(motion.text)}"
        if second:
            line += f"; {second} seconded"
        line += "."
    result = (motion.result or "").strip()
    if result and result != "pending":
        line += f" Motion {result}."
    if motion.yeas or motion.nays or motion.abstain:
        line += f" (Yea {motion.yeas}, Nay {motion.nays}, Abstain {motion.abstain})"
    return line


def _signature_office(meeting: Meeting) -> str:
    office = (meeting.submitted_office or "").strip() or "Adjutant"
    org = (meeting.organization or "").strip()
    if org and "," not in office:
        return f"{office}, {org}"
    return office


def _closing_line(meeting: Meeting, house: MinutesStyle | None = None) -> str:
    if house and house.closing:
        return house.closing
    return ((meeting.minutes_closing or meeting.closing or "").strip())


def apply_minutes_style(meeting: Meeting, house: MinutesStyle) -> Meeting:
    """Copy per-org style onto a meeting for render. Does not touch notes or agenda text."""
    meeting.minutes_name_style = house.name_style
    meeting.minutes_motion_phrasing = house.motion_phrasing
    meeting.minutes_heading_order = list(house.heading_order)
    meeting.minutes_signature_shape = house.signature_shape
    meeting.minutes_closing = house.closing
    return meeting


def _signature_lines(meeting: Meeting, house: MinutesStyle) -> list[str]:
    if not meeting.submitted_by:
        return []
    closing = _closing_line(meeting, house)
    if house.signature_shape == "submitted_by_line":
        lines = [f"**Submitted by {meeting.submitted_by}, {_signature_office(meeting)}.**"]
        if closing:
            lines.extend(["", f"**{closing}**"])
        lines.append("")
        return lines
    lines = [
        "**Respectfully submitted,**",
        "",
        f"**{meeting.submitted_by}**",
        "",
        f"**{_signature_office(meeting)}**",
    ]
    if closing:
        lines.extend(["", f"**{closing}**"])
    lines.append("")
    return lines


def _minutes_sections(meeting: Meeting, house: MinutesStyle) -> dict[str, list[str]]:
    rc = meeting.roll_call()
    names = style_for_names(names_from_meeting(meeting))
    org = meeting.organization or "Organization"
    sections: dict[str, list[str]] = {key: [] for key in DEFAULT_HEADING_ORDER}

    if meeting.called_to_order_by:
        loc = f" at {meeting.location}" if meeting.location else ""
        sections["called_to_order"] = [
            f"**Meeting Called to Order:** The {meeting.title.lower()} of {org} "
            f"was called to order by {meeting.called_to_order_by}{loc}.",
            "",
        ]
    if meeting.opening:
        opening = ["**Opening Ceremonies:**"]
        opening.extend(_bullet(item) for item in meeting.opening)
        opening.append("")
        sections["opening"] = opening

    if meeting.called_to_order_by:
        roll = [f"**Roll Call / Quorum:** {meeting.called_to_order_by} conducted roll call."]
    else:
        roll = ["**Roll Call / Quorum:** Roll was called."]
    roll.append("")
    sections["roll_call"] = roll

    officers = _officer_entries(meeting)
    officer_keys = {normalize_name(name) for name, _title in officers}
    block: list[str] = []
    if officers:
        block.append("**Officers:**")
        for name, title in officers:
            labeled = f"{title} {names.roll(name)}".strip()
            block.append(f"* {labeled}, {_attendance_status(meeting, name)}")
        others = _other_present(meeting, officer_keys)
        if others:
            block.append("")
            guest_names = ", ".join(names.roll(name) for name in others)
            block.append(f"**Members / guests also present:** {guest_names}.")
    else:
        if meeting.present:
            block.extend(
                [
                    "Members present included:",
                    "",
                    ", ".join(names.roll(name) for name in meeting.present) + ".",
                    "",
                ]
            )
        if meeting.late:
            block.extend(["Arrived late: " + ", ".join(names.roll(name) for name in meeting.late) + ".", ""])
        if meeting.guests:
            block.extend(["Guests: " + ", ".join(names.roll(name) for name in meeting.guests) + ".", ""])
        if rc["absent"]:
            block.extend(["Members absent: " + ", ".join(names.roll(name) for name in rc["absent"]) + ".", ""])
    if meeting.org_quorum_line:
        if block and block[-1] != "":
            block.append("")
        block.append(meeting.org_quorum_line)
    elif rc["quorum"]:
        if block and block[-1] != "":
            block.append("")
        block.append(f"A quorum was present ({rc['present_count']} present; {rc['required']} required).")
    else:
        if block and block[-1] != "":
            block.append("")
        block.append(
            f"A quorum was **not** present ({rc['present_count']} present; {rc['required']} required)."
        )
    if officers and rc["absent"] and not any(
        _title_for(meeting, name) and is_officer_title(_title_for(meeting, name)) for name in rc["absent"]
    ):
        block.append("")
        block.append("Members absent: " + ", ".join(names.roll(name) for name in rc["absent"]) + ".")
    block.append("")
    sections["officers"] = block

    prev_map = {
        "approved": "The minutes of the previous meeting were approved as printed.",
        "approved_as_corrected": "The minutes of the previous meeting were approved as corrected.",
        "not_read": "Reading of the previous minutes was dispensed with.",
        "pending": "Approval of the previous minutes is pending.",
    }
    prev = [
        "**Approval of Previous Minutes:** "
        + prev_map.get(meeting.previous_minutes, meeting.previous_minutes)
    ]
    if meeting.previous_minutes_note:
        prev.append(meeting.previous_minutes_note)
    prev.append("")
    sections["previous_minutes"] = prev

    if meeting.reports:
        reports = ["**Reports:**", ""]
        for report in meeting.reports:
            head = report.title
            if report.presenter:
                spoken = _spoken_name(names, report.presenter, house.name_style)
                head = f"{report.title} ({spoken})" if spoken else report.title
            reports.extend(_run_in(head, report.body))
            reports.append("")
        sections["reports"] = reports
    if meeting.old_business:
        old = ["**Old Business:**"]
        old.extend(_bullet(item) for item in meeting.old_business)
        old.append("")
        sections["old_business"] = old
    if meeting.new_business:
        new = ["**New Business:**"]
        for i, motion in enumerate(meeting.new_business, 1):
            new.append(
                f"{i}. {_format_motion(motion, names, house.motion_phrasing, house.name_style)}"
            )
        new.append("")
        sections["new_business"] = new
    if meeting.announcements:
        ann = ["**Announcements / Good of the Order:**"]
        ann.extend(_bullet(item) for item in meeting.announcements)
        ann.append("")
        sections["announcements"] = ann
    if meeting.adjournment:
        sections["adjournment"] = [f"**Adjournment:** {meeting.adjournment}", ""]
    if meeting.takeaways:
        takes = ["**Takeaways / assignments:**"]
        for item in meeting.takeaways:
            extra = f" ({item.owner})" if item.owner else ""
            takes.append(f"* {item.text}{extra}")
        takes.append("")
        sections["takeaways"] = takes
    if meeting.speaker_marks:
        marks = ["**Speaker marks (for review):**"]
        for mark in meeting.speaker_marks:
            mins = int(mark.seconds) // 60
            secs = int(mark.seconds) % 60
            marks.append(f"* {mins:02d}:{secs:02d} {mark.name}")
        marks.append("")
        sections["speaker_marks"] = marks
    sections["signature"] = _signature_lines(meeting, house)
    return sections


def render_minutes(meeting: Meeting, house: MinutesStyle | None = None) -> str:
    """Render formal minutes in the SAL / civic house style used by the adjutant."""
    style = house or minutes_style_from(meeting)
    org = meeting.organization or "Organization"
    lines: list[str] = [f"**{org} Meeting Minutes**"]
    if meeting.date:
        lines.append(f"**{meeting.date}**")
    lines.append("")
    sections = _minutes_sections(meeting, style)
    for key in style.heading_order:
        lines.extend(sections.get(key) or [])
    return "\n".join(lines).rstrip() + "\n"


def email_payload(meeting: Meeting) -> dict[str, str]:
    body = render_minutes(meeting)
    org = meeting.organization or "Meeting"
    date = meeting.date or ""
    subject = f"{org} minutes {date}".strip()
    return {"subject": subject, "body": body, "filename": f"{meeting.file_stem or meeting.id}-minutes.md"}


def render_minutes_html(meeting: Meeting) -> str:
    """Printable HTML for the same minutes (email / paper / PDF via the browser)."""
    md = render_minutes(meeting)
    escaped = (
        md.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    title = f"{meeting.organization or 'Meeting'} minutes {meeting.date or ''}".strip()
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<title>{title}</title>"
        "<style>body{font:16px/1.45 Georgia,serif;max-width:40rem;margin:2rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap;font:inherit}</style></head><body>"
        f"<pre>{escaped}</pre></body></html>\n"
    )
