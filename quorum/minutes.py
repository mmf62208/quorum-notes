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


DOC_LABELS = ("finance", "agenda", "handout", "other")


def normalize_doc_label(label: str) -> str:
    key = (label or "other").strip().casefold()
    return key if key in DOC_LABELS else "other"


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


def _format_motion(motion: Motion, style: NameStyle) -> str:
    who = style.spoken(motion.mover) or "A member"
    line = f"{who} {_motion_clause(motion.text)}"
    if (motion.seconder or "").strip():
        line += f"; {style.spoken(motion.seconder)} seconded"
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


def _closing_line(meeting: Meeting) -> str:
    return ((meeting.minutes_closing or meeting.closing or "").strip())


def render_minutes(meeting: Meeting) -> str:
    """Render formal minutes in the SAL / civic house style used by the adjutant."""
    rc = meeting.roll_call()
    style = style_for_names(names_from_meeting(meeting))
    lines: list[str] = []
    org = meeting.organization or "Organization"
    lines.append(f"**{org} Meeting Minutes**")
    if meeting.date:
        lines.append(f"**{meeting.date}**")
    lines.append("")
    if meeting.called_to_order_by:
        loc = f" at {meeting.location}" if meeting.location else ""
        lines.append(
            f"**Meeting Called to Order:** The {meeting.title.lower()} of {org} "
            f"was called to order by {meeting.called_to_order_by}{loc}."
        )
        lines.append("")
    if meeting.opening:
        lines.append("**Opening Ceremonies:**")
        for item in meeting.opening:
            lines.append(_bullet(item))
        lines.append("")
    if meeting.called_to_order_by:
        lines.append(f"**Roll Call / Quorum:** {meeting.called_to_order_by} conducted roll call.")
    else:
        lines.append("**Roll Call / Quorum:** Roll was called.")
    officers = _officer_entries(meeting)
    officer_keys = {normalize_name(name) for name, _title in officers}
    if officers:
        lines.append("**Officers:**")
        for name, title in officers:
            labeled = f"{title} {style.roll(name)}".strip()
            lines.append(f"* {labeled}, {_attendance_status(meeting, name)}")
        others = _other_present(meeting, officer_keys)
        if others:
            lines.append("")
            guest_names = ", ".join(style.roll(name) for name in others)
            lines.append(f"**Members / guests also present:** {guest_names}.")
    else:
        if meeting.present:
            lines.append("Members present included:")
            lines.append("")
            lines.append(", ".join(style.roll(name) for name in meeting.present) + ".")
            lines.append("")
        if meeting.late:
            lines.append("Arrived late: " + ", ".join(style.roll(name) for name in meeting.late) + ".")
            lines.append("")
        if meeting.guests:
            lines.append("Guests: " + ", ".join(style.roll(name) for name in meeting.guests) + ".")
            lines.append("")
        if rc["absent"]:
            lines.append("Members absent: " + ", ".join(style.roll(name) for name in rc["absent"]) + ".")
            lines.append("")
    if meeting.org_quorum_line:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(meeting.org_quorum_line)
    elif rc["quorum"]:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(
            f"A quorum was present ({rc['present_count']} present; {rc['required']} required)."
        )
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(
            f"A quorum was **not** present ({rc['present_count']} present; {rc['required']} required)."
        )
    if officers and rc["absent"] and not any(_title_for(meeting, name) and is_officer_title(_title_for(meeting, name)) for name in rc["absent"]):
        lines.append("")
        lines.append("Members absent: " + ", ".join(style.roll(name) for name in rc["absent"]) + ".")
    lines.append("")
    prev_map = {
        "approved": "The minutes of the previous meeting were approved as printed.",
        "approved_as_corrected": "The minutes of the previous meeting were approved as corrected.",
        "not_read": "Reading of the previous minutes was dispensed with.",
        "pending": "Approval of the previous minutes is pending.",
    }
    lines.append(
        "**Approval of Previous Minutes:** "
        + prev_map.get(meeting.previous_minutes, meeting.previous_minutes)
    )
    if meeting.previous_minutes_note:
        lines.append(meeting.previous_minutes_note)
    lines.append("")
    if meeting.reports:
        lines.append("**Reports:**")
        lines.append("")
        for report in meeting.reports:
            head = report.title
            if report.presenter:
                spoken = style.spoken(report.presenter)
                head = f"{report.title} ({spoken})" if spoken else report.title
            lines.extend(_run_in(head, report.body))
            lines.append("")
    if meeting.old_business:
        lines.append("**Old Business:**")
        for item in meeting.old_business:
            lines.append(_bullet(item))
        lines.append("")
    if meeting.new_business:
        lines.append("**New Business:**")
        for i, motion in enumerate(meeting.new_business, 1):
            lines.append(f"{i}. {_format_motion(motion, style)}")
        lines.append("")
    if meeting.announcements:
        lines.append("**Announcements / Good of the Order:**")
        for item in meeting.announcements:
            lines.append(_bullet(item))
        lines.append("")
    if meeting.adjournment:
        lines.append(f"**Adjournment:** {meeting.adjournment}")
        lines.append("")
    if meeting.takeaways:
        lines.append("**Takeaways / assignments:**")
        for item in meeting.takeaways:
            extra = f" ({item.owner})" if item.owner else ""
            lines.append(f"* {item.text}{extra}")
        lines.append("")
    if meeting.speaker_marks:
        lines.append("**Speaker marks (for review):**")
        for mark in meeting.speaker_marks:
            mins = int(mark.seconds) // 60
            secs = int(mark.seconds) % 60
            lines.append(f"* {mins:02d}:{secs:02d} {mark.name}")
        lines.append("")
    if meeting.submitted_by:
        lines.append("**Respectfully submitted,**")
        lines.append("")
        lines.append(f"**{meeting.submitted_by}**")
        lines.append("")
        lines.append(f"**{_signature_office(meeting)}**")
        closing = _closing_line(meeting)
        if closing:
            lines.append("")
            lines.append(f"**{closing}**")
        lines.append("")
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
