"""When to delete the meeting tape. Minutes and photos stay."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

POLICIES = ("until_approved", "7d", "14d", "keep")


def should_delete_audio(
    policy: str,
    *,
    minutes_approved: bool,
    recorded_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return True if the WAV should be removed under the user's retention choice."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if recorded_at is not None and recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    if policy == "keep":
        return False
    if policy == "until_approved":
        return bool(minutes_approved)
    if policy == "7d":
        return bool(recorded_at and now >= recorded_at + timedelta(days=7))
    if policy == "14d":
        return bool(recorded_at and now >= recorded_at + timedelta(days=14))
    return False
