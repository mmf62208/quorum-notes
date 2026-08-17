import tempfile
import unittest
from pathlib import Path

from quorum import backup, config, gold, settings as app_settings, signin, vault
from quorum.minutes import Meeting, Motion, Report, render_minutes


class SigninMergeTests(unittest.TestCase):
    def test_matches_roster_and_keeps_unmatched(self):
        roster = ["Mike Featherstone", "Jeff Shumaker", "Herm Clear"]
        result = signin.merge_present(roster, ["Jeff Shumaker"], ["mike featherstone", "Unknown Guest"])
        self.assertIn("Mike Featherstone", result["present"])
        self.assertIn("Jeff Shumaker", result["present"])
        self.assertEqual(result["matched"], ["Mike Featherstone"])
        self.assertEqual(result["unmatched"], ["Unknown Guest"])
        self.assertNotIn("Unknown Guest", result["present"])


class GoldMinutesTests(unittest.TestCase):
    def test_june16_shape_passes_and_empty_fails(self):
        meeting = Meeting(
            id="gold",
            organization="SAL Post 484 Squadron",
            date="2026-06-16",
            title="Regular Meeting",
            called_to_order_by="Commander Jeff Shumaker",
            location="Post home",
            opening=["Chaplain Herm Clear offered the opening prayer."],
            roster=["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser", "William Wood"],
            present=["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser", "William Wood"],
            previous_minutes="approved",
            reports=[Report(title="Finance", presenter="Ted Ruser", body="Checking ending $6,171.18")],
            new_business=[
                Motion(
                    text="SAL cover VA veterans’ meals",
                    mover="William Wood",
                    seconder="Herm Clear",
                    yeas=10,
                    nays=0,
                    result="carried",
                )
            ],
            submitted_by="Mike Featherstone",
            submitted_office="Adjutant, SAL Post 484",
        )
        text = render_minutes(meeting)
        self.assertTrue(gold.is_sal_shaped(text), gold.missing_sal_phrases(text))
        self.assertIn("SAL Post 484", text)
        self.assertEqual(gold.missing_sal_phrases("scratch notes"), list(gold.REQUIRED_SAL_PHRASES))


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.prev_v = config.os.environ.get("QUORUM_VAULT")
        self.prev_b = config.os.environ.get("QUORUM_BACKUPS")
        config.os.environ["QUORUM_VAULT"] = str(root / "vault")
        config.os.environ["QUORUM_BACKUPS"] = str(root / "backups")

    def tearDown(self):
        if self.prev_v is None:
            config.os.environ.pop("QUORUM_VAULT", None)
        else:
            config.os.environ["QUORUM_VAULT"] = self.prev_v
        if self.prev_b is None:
            config.os.environ.pop("QUORUM_BACKUPS", None)
        else:
            config.os.environ["QUORUM_BACKUPS"] = self.prev_b
        self.tmp.cleanup()

    def test_backup_roundtrip_restores_meeting(self):
        app_settings.save_settings({"setup_complete": True, "organization": "SAL Post 484 Squadron"})
        meeting = vault.create_meeting({"title": "Regular Meeting", "organization": "SAL Post 484 Squadron"})
        mid = meeting.id
        archive = backup.make_backup()
        self.assertTrue(archive.is_file())
        vault.delete_meeting(mid)
        with self.assertRaises(FileNotFoundError):
            vault.load_meeting(mid)
        restored = backup.restore_backup(archive)
        self.assertGreater(restored, 0)
        again = vault.load_meeting(mid)
        self.assertEqual(again.organization, "SAL Post 484 Squadron")


if __name__ == "__main__":
    unittest.main()
