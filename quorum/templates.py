"""Org templates applied when a meeting is created."""

from __future__ import annotations

SAL_OPENING = [
    "Chaplain offered the opening prayer.",
    "The Commander led the Pledge of Allegiance.",
    "A moment of silence was observed in honor of POW/MIA.",
]

GENERIC_OPENING = [
    "The meeting was opened and the roll was called.",
]


def opening_for(template: str) -> list[str]:
    if template == "sal":
        return list(SAL_OPENING)
    if template == "generic":
        return list(GENERIC_OPENING)
    return []
