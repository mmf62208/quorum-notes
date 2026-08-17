"""A scripted Post 484 dry-run so testers can walk a whole meeting."""

from __future__ import annotations

from .minutes import Motion, Report
from .templates import SAL_OPENING
from . import settings as app_settings
from . import vault


def seed_post484_dry_run() -> object:
    prefs = app_settings.load_settings()
    roster = list(prefs.get("roster") or [])
    if len(roster) < 3:
        roster = [
            "Jeff Shumaker",
            "Herm Clear",
            "Mike Featherstone",
            "Ted Ruser",
            "William Wood",
        ]
    present = roster[: max(3, min(len(roster), 5))]
    meeting = vault.create_meeting(
        {
            "title": "Dry-run Regular Meeting",
            "organization": prefs.get("organization") or "SAL Post 484 Squadron",
            "location": prefs.get("default_location") or "Post home",
            "called_to_order_by": prefs.get("called_to_order_by") or "Commander Jeff Shumaker",
            "submitted_by": prefs.get("submitted_by") or "Mike Featherstone",
            "submitted_office": prefs.get("submitted_office") or "Adjutant, SAL Post 484",
            "roster": roster,
            "present": present,
            "opening": list(SAL_OPENING),
            "previous_minutes": "pending",
            "reports": [
                Report(
                    title="Finance",
                    presenter="Ted Ruser",
                    body="Checking and savings reports are ready for the floor.",
                )
            ],
            "old_business": ["Need for volunteers remains open."],
            "new_business": [
                Motion(
                    text="the Squadron practice the new minutes workflow at this meeting",
                    mover=present[0],
                    seconder=present[1] if len(present) > 1 else "",
                    result="pending",
                )
            ],
            "notes": "Dry-run: walk Opening → Roll call → Previous minutes → Reports → Motions → Adjourn → Email.",
            "agenda_index": 0,
        }
    )
    return meeting
