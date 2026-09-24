"""JS/layout contract: Record stays gated until a meeting is open; Stop does not lie."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "quorum" / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "quorum" / "web" / "index.html").read_text(encoding="utf-8")


def _fn(source: str, name: str) -> str:
    marker = f"async function {name}"
    start = source.index(marker)
    nxt = re.search(r"\n(?:async )?function ", source[start + len(marker) :])
    return source[start : start + len(marker) + (nxt.start() if nxt else len(source))]


class RecordGateContractTests(unittest.TestCase):
    def test_record_button_starts_disabled(self):
        self.assertRegex(INDEX, r'id="btn-rec"[^>]*\bdisabled\b')
        self.assertIn("Start meeting first, then Record", INDEX)

    def test_start_rec_ignores_clicks_without_meeting(self):
        start = _fn(APP_JS, "startRec")
        self.assertIn("hasOpenMeeting()", start)
        self.assertIn("return", start)
        self.assertIn("Start meeting first, then Record", start)
        self.assertLess(start.index("hasOpenMeeting()"), start.index("openMic(true)"))

    def test_stop_claims_saved_only_after_api_ok(self):
        stop = _fn(APP_JS, "stopRec")
        self.assertIn("Nothing captured", stop)
        self.assertIn("Could not save recording", stop)
        self.assertIn("await api(`/api/meetings/${current.id}/audio`", stop)
        self.assertNotIn("await fetch(`/api/meetings/${current.id}/audio`", stop)
        self.assertLess(stop.index("await api("), stop.index("Saved recording"))
        self.assertLess(stop.index("Saved recording"), stop.index("} catch"))


if __name__ == "__main__":
    unittest.main()
