"""Light Robert’s Rules / SAL order of business."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .minutes import Meeting

STEPS: tuple[tuple[str, str], ...] = (
    ("opening", "Opening"),
    ("roll_call", "Roll call"),
    ("previous_minutes", "Previous minutes"),
    ("reports", "Reports"),
    ("old_business", "Old business"),
    ("new_business", "New business"),
    ("announcements", "Good of the order"),
    ("adjournment", "Adjourn"),
)

STEP_IDS = [s[0] for s in STEPS]


def step_done(meeting: Meeting, step_id: str) -> bool:
    if step_id == "opening":
        return bool(meeting.opening) and bool(meeting.called_to_order_by)
    if step_id == "roll_call":
        return bool(meeting.present)
    if step_id == "previous_minutes":
        return meeting.previous_minutes != "pending"
    if step_id == "reports":
        return bool(meeting.reports)
    if step_id == "old_business":
        return True
    if step_id == "new_business":
        return any(m.result in {"carried", "failed", "withdrawn", "tabled"} for m in meeting.new_business)
    if step_id == "announcements":
        return True
    if step_id == "adjournment":
        return bool((meeting.adjournment or "").strip())
    return False


def agenda_status(meeting: Meeting) -> list[dict[str, object]]:
    return [
        {"id": sid, "label": label, "done": step_done(meeting, sid)}
        for sid, label in STEPS
    ]


def clamp_agenda_index(index: int) -> int:
    if index < 0:
        return 0
    if index >= len(STEPS):
        return len(STEPS) - 1
    return index


def next_index(index: int) -> int:
    return clamp_agenda_index(index + 1)


def prev_index(index: int) -> int:
    return clamp_agenda_index(index - 1)
