import tempfile
import unittest
from pathlib import Path

from quorum import config, demo, settings as app_settings, vault
from quorum.agenda import STEP_IDS, agenda_status, next_index, prev_index, step_done
from quorum.minutes import Meeting, Motion, Report


class AgendaTests(unittest.TestCase):
    def test_step_order(self):
        self.assertEqual(STEP_IDS[0], "opening")
        self.assertEqual(STEP_IDS[-1], "adjournment")
        self.assertEqual(next_index(0), 1)
        self.assertEqual(prev_index(0), 0)
        self.assertEqual(next_index(99), len(STEP_IDS) - 1)

    def test_step_done_from_meeting_fields(self):
        meeting = Meeting(id="a")
        self.assertFalse(step_done(meeting, "opening"))
        meeting.opening = ["Prayer."]
        meeting.called_to_order_by = "Commander"
        self.assertTrue(step_done(meeting, "opening"))
        self.assertFalse(step_done(meeting, "roll_call"))
        meeting.present = ["Mike"]
        self.assertTrue(step_done(meeting, "roll_call"))
        self.assertFalse(step_done(meeting, "previous_minutes"))
        meeting.previous_minutes = "approved"
        self.assertTrue(step_done(meeting, "previous_minutes"))
        meeting.reports = [Report(title="Finance", presenter="Ted", body="ok")]
        self.assertTrue(step_done(meeting, "reports"))
        meeting.new_business = [Motion(text="x", mover="A", seconder="B", result="carried")]
        self.assertTrue(step_done(meeting, "new_business"))
        meeting.adjournment = "Adjourned."
        self.assertTrue(step_done(meeting, "adjournment"))
        status = agenda_status(meeting)
        self.assertEqual(len(status), len(STEP_IDS))
        self.assertTrue(all("id" in s and "done" in s for s in status))


class DemoMeetingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = config.os.environ.get("QUORUM_VAULT")
        config.os.environ["QUORUM_VAULT"] = str(Path(self.tmp.name) / "vault")

    def tearDown(self):
        if self.prev is None:
            config.os.environ.pop("QUORUM_VAULT", None)
        else:
            config.os.environ["QUORUM_VAULT"] = self.prev
        self.tmp.cleanup()

    def test_dry_run_has_sal_shape(self):
        app_settings.save_settings(
            {
                "setup_complete": True,
                "organization": "SAL Post 484 Squadron",
                "template": "sal",
                "roster": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"],
            }
        )
        meeting = demo.seed_post484_dry_run()
        self.assertTrue(meeting.present)
        self.assertTrue(meeting.opening)
        self.assertTrue(meeting.reports)
        self.assertTrue(meeting.new_business)
        self.assertIn("Dry-run", meeting.title)
        md = (config.vault_dir() / "meetings" / meeting.id / "minutes.md").read_text(encoding="utf-8")
        self.assertIn("Roll Call / Quorum", md)
        self.assertIn("Finance", md)


if __name__ == "__main__":
    unittest.main()
