import tempfile
import unittest
from pathlib import Path

from quorum import config, settings as app_settings, vault
from quorum.naming import meeting_stem


class SettingsPersistTests(unittest.TestCase):
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

    def test_save_and_load_org_roster_and_each_retention(self):
        roster = ["Mike Featherstone", "Jeff Shumaker", "Herm Clear"]
        for choice in ("until_approved", "7d", "14d", "keep"):
            saved = app_settings.save_settings(
                {
                    "setup_complete": True,
                    "organization": "SAL Post 484 Squadron",
                    "roster": roster,
                    "retention": choice,
                }
            )
            self.assertEqual(saved["organization"], "SAL Post 484 Squadron")
            self.assertEqual(saved["roster"], roster)
            self.assertEqual(saved["retention"], choice)
            loaded = app_settings.load_settings()
            self.assertEqual(loaded["organization"], "SAL Post 484 Squadron")
            self.assertEqual(loaded["roster"], roster)
            self.assertEqual(loaded["retention"], choice)
            self.assertTrue((config.vault_dir() / "settings.json").is_file())

    def test_invalid_retention_rejected(self):
        with self.assertRaises(ValueError):
            app_settings.save_settings({"retention": "forever"})


class CreateMeetingNamingTests(unittest.TestCase):
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

    def test_create_meeting_auto_names_and_sets_date(self):
        meeting = vault.create_meeting(
            {"title": "Regular Meeting", "organization": "SAL Post 484 Squadron"}
        )
        self.assertTrue(meeting.date)
        self.assertRegex(meeting.date, r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(meeting.file_stem)
        self.assertIn("SAL-Post-484-Squadron", meeting.file_stem)
        self.assertIn("Regular-Meeting", meeting.file_stem)
        prefix = meeting_stem("SAL Post 484 Squadron", "Regular Meeting")[:10]
        self.assertTrue(meeting.file_stem.startswith(prefix))
        self.assertTrue((config.vault_dir() / "meetings" / meeting.id / "minutes.md").is_file())
        md = (config.vault_dir() / "meetings" / meeting.id / "minutes.md").read_text(encoding="utf-8")
        self.assertIn("Meeting Minutes", md)
        self.assertIn("Roll Call / Quorum", md)


if __name__ == "__main__":
    unittest.main()
