import unittest
from datetime import datetime

from quorum.minutes import Meeting, Motion, email_payload
from quorum.naming import meeting_stem, slug
from quorum.settings import DEFAULTS, RETENTION_CHOICES


class NamingTests(unittest.TestCase):
    def test_stem(self):
        when = datetime(2026, 9, 15, 19, 0)
        self.assertEqual(
            meeting_stem("SAL Post 484 Squadron", "Regular Meeting", when),
            "2026-09-15_SAL-Post-484-Squadron_Regular-Meeting_1900",
        )

    def test_slug_fallback(self):
        self.assertEqual(slug("@@@"), "Meeting")


class EmailTests(unittest.TestCase):
    def test_email_includes_minutes(self):
        meeting = Meeting(
            id="x",
            file_stem="2026-09-15_SAL_Regular-Meeting_1900",
            organization="SAL Post 484 Squadron",
            date="2026-09-15",
            present=["Mike Featherstone"],
            roster=["Mike Featherstone", "Jeff Shumaker"],
            new_business=[
                Motion(text="buy lumber", mover="Herm", seconder="Mike", result="carried")
            ],
        )
        mail = email_payload(meeting)
        self.assertIn("SAL Post 484", mail["subject"])
        self.assertIn("Herm moved", mail["body"])
        self.assertTrue(mail["filename"].endswith(".md"))


class SettingsTests(unittest.TestCase):
    def test_retention_choices(self):
        self.assertIn("until_approved", RETENTION_CHOICES)
        self.assertIn("7d", RETENTION_CHOICES)
        self.assertIn(DEFAULTS["retention"], RETENTION_CHOICES)


if __name__ == "__main__":
    unittest.main()
