"""Checks that minutes still look like civic / SAL minutes an adjutant would file."""

from __future__ import annotations

REQUIRED_SAL_PHRASES = (
    "Meeting Minutes",
    "Roll Call / Quorum",
    "Approval of Previous Minutes",
    "New Business",
    "moved that",
    "seconded",
    "Respectfully submitted",
)


def missing_sal_phrases(minutes_text: str) -> list[str]:
    text = minutes_text or ""
    return [phrase for phrase in REQUIRED_SAL_PHRASES if phrase not in text]


def is_sal_shaped(minutes_text: str) -> bool:
    return not missing_sal_phrases(minutes_text)
