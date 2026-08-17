"""Automatic, human-readable names for meetings and recordings."""

from __future__ import annotations

import re
from datetime import datetime


def slug(text: str, fallback: str = "Meeting") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip())
    cleaned = cleaned.strip("-")
    return (cleaned[:48] or fallback)


def meeting_stem(organization: str, title: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    return "_".join(
        [
            when.strftime("%Y-%m-%d"),
            slug(organization, "Org"),
            slug(title, "Meeting"),
            when.strftime("%H%M"),
        ]
    )


def audio_filename(stem: str) -> str:
    return f"{stem}.wav"
