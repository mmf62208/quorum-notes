"""Formal minutes helpers: roll call / quorum, motions, SAL-style render."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
    notes: str = ""
    late: list[str] = field(default_factory=list)
    guests: list[str] = field(default_factory=list)
    speaker_marks: list[SpeakerMark] = field(default_factory=list)
    takeaways: list[Takeaway] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)
    file_stem: str = ""
    roberts: bool = True
    minutes_approved: bool = False
    has_audio: bool = False
    has_transcript: bool = False
    created_at: str = ""
    updated_at: str = ""

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
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})


def render_minutes(meeting: Meeting) -> str:
    """Render formal minutes in the SAL / civic style used by the adjutant."""
    rc = meeting.roll_call()
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
        lines.append("")
        for item in meeting.opening:
            lines.append(f"* {item}")
        lines.append("")
    lines.append("**Roll Call / Quorum:**")
    if meeting.present:
        lines.append("Members present included:")
        lines.append("")
        lines.append(", ".join(meeting.present) + ".")
        lines.append("")
    if meeting.late:
        lines.append("Arrived late: " + ", ".join(meeting.late) + ".")
        lines.append("")
    if meeting.guests:
        lines.append("Guests: " + ", ".join(meeting.guests) + ".")
        lines.append("")
    if rc["quorum"]:
        lines.append(
            f"A quorum was present ({rc['present_count']} present; {rc['required']} required)."
        )
    else:
        lines.append(
            f"A quorum was **not** present ({rc['present_count']} present; {rc['required']} required)."
        )
    if rc["absent"]:
        lines.append("")
        lines.append("Members absent: " + ", ".join(rc["absent"]) + ".")
    lines.append("")
    prev_map = {
        "approved": "The minutes of the previous meeting were approved as printed.",
        "approved_as_corrected": "The minutes of the previous meeting were approved as corrected.",
        "not_read": "Reading of the previous minutes was dispensed with.",
        "pending": "Approval of the previous minutes is pending.",
    }
    lines.append("**Approval of Previous Minutes:** " + prev_map.get(meeting.previous_minutes, meeting.previous_minutes))
    if meeting.previous_minutes_note:
        lines.append(meeting.previous_minutes_note)
    lines.append("")
    if meeting.reports:
        lines.append("**Reports:**")
        lines.append("")
        for report in meeting.reports:
            head = f"**{report.title}**"
            if report.presenter:
                head += f" ({report.presenter})"
            lines.append(head)
            if report.body:
                lines.append(report.body)
            lines.append("")
    if meeting.old_business:
        lines.append("**Old Business:**")
        lines.append("")
        for item in meeting.old_business:
            lines.append(f"* {item}")
        lines.append("")
    if meeting.new_business:
        lines.append("**New Business:**")
        lines.append("")
        for i, motion in enumerate(meeting.new_business, 1):
            who = motion.mover or "A member"
            line = f"{i}. {who} moved that {motion.text.rstrip('.')}"
            if motion.seconder:
                line += f"; {motion.seconder} seconded"
            line += f". The motion {motion.result}."
            if motion.yeas or motion.nays or motion.abstain:
                line += f" (Yea {motion.yeas}, Nay {motion.nays}, Abstain {motion.abstain})"
            lines.append(line)
        lines.append("")
    if meeting.announcements:
        lines.append("**Announcements / Good of the Order:**")
        lines.append("")
        for item in meeting.announcements:
            lines.append(f"* {item}")
        lines.append("")
    if meeting.adjournment:
        lines.append(f"**Adjournment:** {meeting.adjournment}")
        lines.append("")
    if meeting.closing:
        lines.append(meeting.closing)
        lines.append("")
    if meeting.takeaways:
        lines.append("**Takeaways / assignments:**")
        lines.append("")
        for item in meeting.takeaways:
            who = f" — {item.owner}" if item.owner else ""
            lines.append(f"* {item.text}{who}")
        lines.append("")
    if meeting.speaker_marks:
        lines.append("**Speaker marks (for review):**")
        lines.append("")
        for mark in meeting.speaker_marks:
            mins = int(mark.seconds) // 60
            secs = int(mark.seconds) % 60
            lines.append(f"* {mins:02d}:{secs:02d} — {mark.name}")
        lines.append("")
    if meeting.submitted_by:
        lines.append("**Respectfully submitted,**")
        lines.append("")
        lines.append(f"**{meeting.submitted_by}**")
        if meeting.submitted_office:
            lines.append(f"**{meeting.submitted_office}**")
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
