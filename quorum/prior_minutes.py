"""Prior-minutes style import. Suggestions only — never auto-applied.

Reuses B1 vault upload and the C3 local text extractor. Deterministic parsing
only. No network, no cloud, no AI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import settings as app_settings
from . import vault
from .bylaws import TextExtract, extract_text
from .minutes import (
    DEFAULT_HEADING_ORDER,
    Meeting,
    MinutesStyle,
    Motion,
    apply_minutes_style,
    heading_order_label,
    minutes_style_from,
    normalize_doc_label,
    normalize_heading_order,
    normalize_motion_phrasing,
    normalize_name_style,
    normalize_signature_shape,
    parse_heading_keys,
    render_minutes,
)

PRIOR_LABELS = ("prior_minutes",)

_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("called_to_order", re.compile(r"\b(?:meeting\s+)?called to order\b", re.I)),
    ("opening", re.compile(r"\bopening ceremon", re.I)),
    ("roll_call", re.compile(r"\broll call\b", re.I)),
    ("officers", re.compile(r"^\s*(?:\*{0,2})officers\b", re.I | re.M)),
    ("previous_minutes", re.compile(r"\b(?:approval of\s+)?previous minutes\b", re.I)),
    ("reports", re.compile(r"^\s*(?:\*{0,2})reports\b", re.I | re.M)),
    ("old_business", re.compile(r"\b(?:old|unfinished)\s+business\b", re.I)),
    ("new_business", re.compile(r"\bnew business\b", re.I)),
    ("announcements", re.compile(r"\b(?:announcements|good of the order)\b", re.I)),
    ("adjournment", re.compile(r"\badjourn", re.I)),
    ("takeaways", re.compile(r"\btakeaways?\b", re.I)),
    ("signature", re.compile(r"\b(?:respectfully submitted|submitted by)\b", re.I)),
)

_HEADING_LINE = re.compile(
    r"^\s*(?:\*{0,2})([A-Za-z][A-Za-z0-9 /.'&-]+?)(?:\*{0,2})\s*:",
    re.M,
)
_MOVED_SECONDED = re.compile(
    r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+moved\b[^.\n]{0,240}?;\s*"
    r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+seconded",
    re.I,
)
_MOTION_BY = re.compile(
    r"Motion\s+by\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s*,\s*"
    r"seconded\s+by\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})",
    re.I,
)
_UNFINISHED = re.compile(
    r"\b(tabled|postponed|pending|no motion|no new motion|follow[- ]up|"
    r"next meeting|unfinished|carried over|remains open|still open|"
    r"deferred|held over)\b",
    re.I,
)
_DONE = re.compile(r"\b(carried|approved|adopted|passed|completed|resolved)\b", re.I)
_ITEM_LINE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)(.+?)\s*$")
_BOLD = re.compile(r"\*{1,2}")
_SIGNATURE_SKIP = re.compile(
    r"respectfully submitted|^submitted by\b|^adjutant\b|^secretary\b|"
    r"^commander\b|meeting minutes|^officers\b|^members\b|quorum|"
    r"called to order|^roll call\b|^adjourn",
    re.I,
)
_NAME_LINE = re.compile(r"^[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){1,3}$")

KEEP_FILE_FALLBACK = (
    "The file is kept in the vault. Use the minutes style settings by hand."
)
NO_TEXT_MESSAGE = f"No readable text in this file. {KEEP_FILE_FALLBACK}"
NO_CUES_MESSAGE = f"No style cues found. {KEEP_FILE_FALLBACK}"
OCR_ABSENT_MESSAGE = f"No local OCR tool found (tesseract). {KEEP_FILE_FALLBACK}"
SUGGEST_MESSAGE = (
    "Suggestions only. Confirm or edit before they fill the minutes style or Old Business."
)

_STYLE_FIELDS = (
    "minutes_name_style",
    "minutes_motion_phrasing",
    "minutes_heading_order",
    "minutes_signature_shape",
    "minutes_closing",
)


def is_prior_minutes_label(label: str) -> bool:
    return normalize_doc_label(label) in PRIOR_LABELS


def _plain_line(text: str) -> str:
    return " ".join(_BOLD.sub("", text or "").split()).strip(" .")


def detect_heading_order(text: str) -> list[str]:
    """First-seen section headings, in document order."""
    body = text or ""
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for key, pattern in _HEADING_PATTERNS:
        match = pattern.search(body)
        if not match or key in seen:
            continue
        seen.add(key)
        found.append((match.start(), key))
    for match in _HEADING_LINE.finditer(body):
        label = _plain_line(match.group(1))
        mapped = {
            "meeting called to order": "called_to_order",
            "called to order": "called_to_order",
            "opening ceremonies": "opening",
            "opening": "opening",
            "roll call / quorum": "roll_call",
            "roll call": "roll_call",
            "officers": "officers",
            "approval of previous minutes": "previous_minutes",
            "previous minutes": "previous_minutes",
            "reports": "reports",
            "old business": "old_business",
            "unfinished business": "old_business",
            "new business": "new_business",
            "announcements / good of the order": "announcements",
            "announcements": "announcements",
            "good of the order": "announcements",
            "adjournment": "adjournment",
            "takeaways / assignments": "takeaways",
            "takeaways": "takeaways",
        }.get(label.casefold())
        if not mapped or mapped in seen:
            continue
        seen.add(mapped)
        found.append((match.start(), mapped))
    found.sort(key=lambda row: row[0])
    return [key for _pos, key in found]


def detect_motion_pairs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return phrasing variant and (mover, seconder) pairs."""
    body = text or ""
    by_pairs = [(m.group(1).strip(), m.group(2).strip()) for m in _MOTION_BY.finditer(body)]
    moved_pairs = [(m.group(1).strip(), m.group(2).strip()) for m in _MOVED_SECONDED.finditer(body)]
    if by_pairs and len(by_pairs) >= len(moved_pairs):
        return "motion_by", by_pairs
    if moved_pairs:
        return "moved_seconded", moved_pairs
    if by_pairs:
        return "motion_by", by_pairs
    return "", []


def detect_name_style(pairs: list[tuple[str, str]]) -> str:
    full = 0
    first = 0
    for mover, seconder in pairs:
        for name in (mover, seconder):
            tokens = [tok for tok in name.replace(",", " ").split() if tok]
            if len(tokens) >= 2:
                full += 1
            elif len(tokens) == 1:
                first += 1
    if full > first:
        return "full"
    if first:
        return "first"
    return ""


def detect_signature_shape(text: str) -> str:
    body = text or ""
    if re.search(r"\brespectfully submitted\b", body, re.I):
        return "respectfully"
    if re.search(r"\bsubmitted by\s+[A-Z]", body, re.I):
        return "submitted_by_line"
    return ""


def detect_closing_line(text: str) -> str:
    lines = [_plain_line(ln) for ln in (text or "").replace("\r\n", "\n").split("\n")]
    nonempty = [ln for ln in lines if ln]
    for line in reversed(nonempty[-10:]):
        if _SIGNATURE_SKIP.search(line):
            continue
        if _NAME_LINE.match(line) and len(line.split()) <= 4:
            continue
        if 3 <= len(line) <= 80:
            return line
    return ""


def _section_spans(text: str) -> list[tuple[str, str]]:
    body = (text or "").replace("\r\n", "\n")
    hits: list[tuple[int, str]] = []
    for key, pattern in _HEADING_PATTERNS:
        match = pattern.search(body)
        if match:
            hits.append((match.start(), key))
    hits.sort(key=lambda row: row[0])
    spans: list[tuple[str, str]] = []
    for index, (start, key) in enumerate(hits):
        end = hits[index + 1][0] if index + 1 < len(hits) else len(body)
        spans.append((key, body[start:end]))
    return spans


def _item_lines(block: str) -> list[str]:
    items: list[str] = []
    for raw in (block or "").splitlines()[1:]:
        stripped = raw.strip()
        if not stripped:
            continue
        heading = _HEADING_LINE.match(stripped)
        if heading:
            label = _plain_line(heading.group(1)).casefold()
            if label in {
                "meeting called to order",
                "called to order",
                "opening ceremonies",
                "opening",
                "roll call / quorum",
                "roll call",
                "officers",
                "approval of previous minutes",
                "previous minutes",
                "reports",
                "old business",
                "unfinished business",
                "new business",
                "announcements / good of the order",
                "announcements",
                "good of the order",
                "adjournment",
                "takeaways / assignments",
                "takeaways",
            }:
                break
        match = _ITEM_LINE.match(stripped)
        text = _plain_line(match.group(1) if match else stripped)
        if text:
            items.append(text)
    return items


def detect_old_business(text: str) -> list[str]:
    """Unfinished or tabled items from Old/New Business."""
    found: list[str] = []
    seen: set[str] = set()
    for key, block in _section_spans(text):
        if key not in {"old_business", "new_business"}:
            continue
        for item in _item_lines(block):
            if not _UNFINISHED.search(item):
                continue
            if _DONE.search(item) and not _UNFINISHED.search(item):
                continue
            folded = item.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            found.append(item)
    return found


@dataclass
class DetectedCues:
    heading_order: list[str] = field(default_factory=list)
    motion_phrasing: str = ""
    name_style: str = ""
    signature_shape: str = ""
    closing: str = ""
    old_business: list[str] = field(default_factory=list)
    motion_pairs: list[tuple[str, str]] = field(default_factory=list)

    def has_style(self) -> bool:
        return bool(
            self.heading_order
            or self.motion_phrasing
            or self.name_style
            or self.signature_shape
            or self.closing
        )

    def to_style(self, base: MinutesStyle | None = None) -> MinutesStyle:
        current = base or MinutesStyle()
        return MinutesStyle(
            name_style=self.name_style or current.name_style,
            motion_phrasing=self.motion_phrasing or current.motion_phrasing,
            heading_order=tuple(normalize_heading_order(self.heading_order or list(current.heading_order))),
            signature_shape=self.signature_shape or current.signature_shape,
            closing=self.closing if self.closing else current.closing,
        )


def detect_cues(text: str) -> DetectedCues:
    phrasing, pairs = detect_motion_pairs(text)
    return DetectedCues(
        heading_order=detect_heading_order(text),
        motion_phrasing=phrasing,
        name_style=detect_name_style(pairs),
        signature_shape=detect_signature_shape(text),
        closing=detect_closing_line(text),
        old_business=detect_old_business(text),
        motion_pairs=pairs,
    )


def _field_current(settings: dict[str, Any] | None, field: str) -> Any:
    prefs = settings or {}
    if field not in prefs:
        return None
    return prefs.get(field)


def _style_item(
    field: str,
    label: str,
    proposed: Any,
    proposed_label: str,
    settings: dict[str, Any] | None,
    current_label: str,
) -> dict[str, Any]:
    existing = _field_current(settings, field)
    has_existing = existing not in (None, "", [], ())
    same = False
    if field == "minutes_heading_order":
        same = has_existing and normalize_heading_order(existing) == normalize_heading_order(proposed)
    elif field == "minutes_closing":
        same = has_existing and str(existing).strip() == str(proposed).strip()
    elif has_existing:
        same = str(existing).strip().casefold() == str(proposed).strip().casefold()
    overwrite = has_existing and not same
    change = (
        f"Would replace current {label.lower()} ({current_label}) with: {proposed_label}"
        if overwrite
        else f"Would set {label.lower()}: {proposed_label}"
    )
    return {
        "id": f"style-{field}",
        "kind": "style",
        "field": field,
        "label": label,
        "text": proposed if isinstance(proposed, str) else proposed_label,
        "value": proposed,
        "readonly": False,
        "would_overwrite": overwrite,
        "current": current_label if has_existing else "",
        "proposed": proposed_label,
        "change": change,
    }


def _old_item(index: int, text: str, meeting: Meeting | None) -> dict[str, Any]:
    existing = [str(item or "").strip() for item in ((meeting.old_business if meeting else None) or [])]
    already = text.casefold() in {item.casefold() for item in existing if item}
    return {
        "id": f"old-{index}",
        "kind": "old_business",
        "text": text,
        "value": text,
        "readonly": False,
        "would_overwrite": False,
        "already": already,
        "current": text if already else "",
        "proposed": text,
        "change": (
            "Already on this meeting's Old Business."
            if already
            else "Would add to this meeting's Old Business."
        ),
    }


def sample_preview_meeting() -> Meeting:
    return Meeting(
        id="style-preview",
        title="Regular Meeting",
        organization="Example Squadron 12",
        date="September 22, 2026",
        location="Post home",
        called_to_order_by="Commander Pat Hale",
        roster=["Pat Hale", "Herm Walsh", "Randy Cole", "Mike Foster"],
        present=["Pat Hale", "Herm Walsh", "Randy Cole", "Mike Foster"],
        previous_minutes="approved",
        old_business=["Kitchen utilities: no new motion."],
        new_business=[
            Motion(
                text="accept the financial report as presented",
                mover="Herm Walsh",
                seconder="Randy Cole",
                yeas=4,
                nays=0,
                result="carried",
            )
        ],
        adjournment="With no further business, the meeting was adjourned.",
        submitted_by="Mike Foster",
        submitted_office="Adjutant",
        minutes_closing="",
    )


def meeting_for_preview(meeting: Meeting | None) -> Meeting:
    if meeting and (meeting.new_business or meeting.submitted_by or meeting.old_business or meeting.reports):
        return Meeting.from_dict(meeting.to_dict())
    return sample_preview_meeting()


def preview_renders(
    meeting: Meeting | None,
    current_settings: dict[str, Any] | None,
    proposed: MinutesStyle,
) -> dict[str, str]:
    source = meeting_for_preview(meeting)
    before_meeting = Meeting.from_dict(source.to_dict())
    after_meeting = Meeting.from_dict(source.to_dict())
    apply_minutes_style(before_meeting, minutes_style_from(current_settings or {}))
    apply_minutes_style(after_meeting, proposed)
    return {
        "before": render_minutes(before_meeting),
        "after": render_minutes(after_meeting),
    }


def proposed_style_from_items(
    settings: dict[str, Any] | None,
    items: list[dict[str, Any]],
) -> MinutesStyle:
    base = minutes_style_from(settings or {})
    data = base.to_dict()
    for item in items:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "")
        if field not in _STYLE_FIELDS:
            continue
        if field == "minutes_heading_order":
            data[field] = item.get("value") or item.get("text")
        else:
            data[field] = item.get("value") if "value" in item else item.get("text")
    return minutes_style_from(data)


@dataclass
class PriorMinutesScan:
    filename: str = ""
    label: str = ""
    text: str = ""
    extractor: str = "none"
    tools_missing: tuple[str, ...] = ()
    found: bool = False
    message: str = NO_TEXT_MESSAGE
    style: list[dict[str, Any]] = field(default_factory=list)
    old_business: list[dict[str, Any]] = field(default_factory=list)
    preview: dict[str, str] = field(default_factory=dict)
    cues: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "label": self.label,
            "text": self.text,
            "extractor": self.extractor,
            "tools_missing": list(self.tools_missing),
            "found": self.found,
            "message": self.message,
            "style": list(self.style),
            "old_business": list(self.old_business),
            "preview": dict(self.preview),
            "cues": dict(self.cues),
        }


def _failure_message(extracted: TextExtract) -> str:
    if extracted.text.strip():
        return NO_CUES_MESSAGE
    if extracted.tools_missing == ("tesseract",):
        return OCR_ABSENT_MESSAGE
    if extracted.tools_missing:
        missing = ", ".join(extracted.tools_missing)
        return f"No readable text in this file (missing local tools: {missing}). {KEEP_FILE_FALLBACK}"
    return NO_TEXT_MESSAGE


def _style_suggestions(cues: DetectedCues, settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    current = minutes_style_from(settings or {})
    items: list[dict[str, Any]] = []
    if cues.heading_order:
        items.append(
            _style_item(
                "minutes_heading_order",
                "Heading order",
                list(cues.heading_order),
                heading_order_label(cues.heading_order),
                settings,
                heading_order_label(current.heading_order),
            )
        )
    if cues.motion_phrasing:
        labels = {
            "moved_seconded": "X moved …; Y seconded",
            "motion_by": "Motion by X, seconded by Y",
        }
        items.append(
            _style_item(
                "minutes_motion_phrasing",
                "Motion phrasing",
                cues.motion_phrasing,
                labels.get(cues.motion_phrasing, cues.motion_phrasing),
                settings,
                labels.get(current.motion_phrasing, current.motion_phrasing),
            )
        )
    if cues.name_style:
        labels = {"first": "First names when unique", "full": "Full names"}
        items.append(
            _style_item(
                "minutes_name_style",
                "Name style",
                cues.name_style,
                labels.get(cues.name_style, cues.name_style),
                settings,
                labels.get(current.name_style, current.name_style),
            )
        )
    if cues.signature_shape:
        labels = {
            "respectfully": "Respectfully submitted block",
            "submitted_by_line": "Submitted by Name, Office",
        }
        items.append(
            _style_item(
                "minutes_signature_shape",
                "Signature block",
                cues.signature_shape,
                labels.get(cues.signature_shape, cues.signature_shape),
                settings,
                labels.get(current.signature_shape, current.signature_shape),
            )
        )
    if cues.closing:
        items.append(
            _style_item(
                "minutes_closing",
                "Closing line",
                cues.closing,
                cues.closing,
                settings,
                current.closing or "(none)",
            )
        )
    return items


def scan_text(
    text: str,
    filename: str = "",
    label: str = "prior_minutes",
    settings: dict[str, Any] | None = None,
    meeting: Meeting | None = None,
    extractor: str = "text",
    tools_missing: tuple[str, ...] = (),
) -> PriorMinutesScan:
    """Pure pattern match. Does not write settings, vault, or agenda items."""
    body = text or ""
    cues = detect_cues(body)
    style_items = _style_suggestions(cues, settings)
    old_items = [_old_item(i, item, meeting) for i, item in enumerate(cues.old_business)]
    found = bool(style_items or old_items)
    extracted = TextExtract(text=body, extractor=extractor, tools_missing=tools_missing)
    proposed = cues.to_style(minutes_style_from(settings or {}))
    return PriorMinutesScan(
        filename=filename,
        label=normalize_doc_label(label) if label else "",
        text=body,
        extractor=extractor,
        tools_missing=tools_missing,
        found=found,
        message=SUGGEST_MESSAGE if found else _failure_message(extracted),
        style=style_items,
        old_business=old_items,
        preview=preview_renders(meeting, settings, proposed) if found else {"before": "", "after": ""},
        cues={
            "heading_order": list(cues.heading_order),
            "motion_phrasing": cues.motion_phrasing,
            "name_style": cues.name_style,
            "signature_shape": cues.signature_shape,
            "closing": cues.closing,
            "old_business": list(cues.old_business),
        },
    )


def scan_bytes(
    data: bytes,
    filename: str = "",
    label: str = "prior_minutes",
    settings: dict[str, Any] | None = None,
    meeting: Meeting | None = None,
) -> PriorMinutesScan:
    extracted = extract_text(data, filename=filename)
    return scan_text(
        extracted.text,
        filename=filename,
        label=label,
        settings=settings,
        meeting=meeting,
        extractor=extracted.extractor,
        tools_missing=extracted.tools_missing,
    )


@dataclass
class ApplyPlan:
    update: dict[str, Any] = field(default_factory=dict)
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    old_business: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    meeting: Meeting | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "update": dict(self.update),
            "applied": list(self.applied),
            "skipped": list(self.skipped),
            "old_business": list(self.old_business),
            "settings": dict(self.settings),
        }
        if self.meeting is not None:
            payload["meeting"] = self.meeting.to_dict()
            payload["markdown"] = render_minutes(self.meeting)
        return payload


def _coerce_style_value(field: str, raw: Any) -> Any:
    if field == "minutes_heading_order":
        keys = parse_heading_keys(raw)
        return keys or list(DEFAULT_HEADING_ORDER)
    if field == "minutes_name_style":
        return normalize_name_style(raw)
    if field == "minutes_motion_phrasing":
        return normalize_motion_phrasing(raw)
    if field == "minutes_signature_shape":
        return normalize_signature_shape(raw)
    if field == "minutes_closing":
        return " ".join(str(raw or "").split()).strip()
    return raw


def plan_apply(
    settings: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    meeting: Meeting | None = None,
) -> ApplyPlan:
    """Decide what confirm would write. Never writes."""
    prefs = dict(settings or {})
    body = dict(payload or {})
    plan = ApplyPlan()

    for raw in body.get("style") or []:
        if not isinstance(raw, dict) or not raw.get("confirm"):
            continue
        field = str(raw.get("field") or "")
        if field not in _STYLE_FIELDS:
            plan.skipped.append({"kind": "style", "field": field, "reason": "unknown"})
            continue
        value = _coerce_style_value(field, raw.get("value") if "value" in raw else raw.get("text"))
        existing = prefs.get(field)
        has_existing = field in prefs and existing not in (None, "", [], ())
        if has_existing and not raw.get("overwrite"):
            current_same = existing == value
            if field == "minutes_heading_order":
                current_same = normalize_heading_order(existing) == normalize_heading_order(value)
            elif field == "minutes_closing":
                current_same = str(existing).strip() == str(value).strip()
            if current_same:
                plan.skipped.append({"kind": "style", "field": field, "reason": "same"})
                continue
            plan.skipped.append(
                {
                    "kind": "style",
                    "field": field,
                    "reason": "exists",
                    "current": existing,
                    "proposed": value,
                    "change": f"Current {field} was left unchanged.",
                }
            )
            continue
        plan.update[field] = value
        plan.applied.append({"kind": "style", "field": field, "value": value, "overwrote": has_existing})

    existing_old = [str(item or "").strip() for item in ((meeting.old_business if meeting else None) or [])]
    keys = {item.casefold() for item in existing_old if item}
    added: list[str] = []
    for raw in body.get("old_business") or []:
        if not isinstance(raw, dict) or not raw.get("confirm"):
            continue
        text = " ".join(str(raw.get("text") or raw.get("value") or "").split()).strip()
        if not text:
            plan.skipped.append({"kind": "old_business", "reason": "empty"})
            continue
        if text.casefold() in keys:
            plan.skipped.append(
                {
                    "kind": "old_business",
                    "reason": "exists",
                    "text": text,
                    "change": "Already on this meeting's Old Business.",
                }
            )
            continue
        added.append(text)
        keys.add(text.casefold())
        plan.applied.append({"kind": "old_business", "text": text})
    plan.old_business = existing_old + added
    return plan


def apply_confirmed(
    settings: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    meeting: Meeting | None = None,
) -> ApplyPlan:
    """Write confirmed style settings and, if a meeting is given, Old Business items."""
    prefs = settings if settings is not None else app_settings.load_settings()
    plan = plan_apply(prefs, payload, meeting)
    if plan.update:
        plan.settings = app_settings.save_settings(plan.update)
    else:
        plan.settings = dict(prefs)
    target = meeting
    meeting_id = str((payload or {}).get("meeting_id") or "")
    if target is None and meeting_id:
        try:
            target = vault.load_meeting(meeting_id)
        except (FileNotFoundError, ValueError):
            target = None
    if target is not None:
        notes = target.notes
        confirmed_old = any(
            isinstance(row, dict) and row.get("confirm") for row in (payload or {}).get("old_business") or []
        )
        if confirmed_old:
            target.old_business = list(plan.old_business)
        house = minutes_style_from(plan.settings)
        if plan.update:
            apply_minutes_style(target, house)
        target.notes = notes
        plan.meeting = vault.save_meeting(target)
        plan.old_business = list(plan.meeting.old_business or [])
    return plan


def preview_from_payload(
    settings: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    meeting: Meeting | None = None,
) -> dict[str, str]:
    items = []
    for raw in (payload or {}).get("style") or []:
        if isinstance(raw, dict) and raw.get("confirm"):
            items.append(raw)
    proposed = proposed_style_from_items(settings, items)
    return preview_renders(meeting, settings, proposed)
