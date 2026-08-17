import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quorum import config, settings as app_settings, vault
from quorum.retention import should_delete_audio
from quorum.templates import SAL_OPENING, opening_for


class RetentionPolicyTests(unittest.TestCase):
    def test_keep_never_deletes(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        old = now - timedelta(days=40)
        self.assertFalse(
            should_delete_audio("keep", minutes_approved=True, recorded_at=old, now=now)
        )

    def test_until_approved_only_after_approve(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        rec = now - timedelta(hours=1)
        self.assertFalse(
            should_delete_audio("until_approved", minutes_approved=False, recorded_at=rec, now=now)
        )
        self.assertTrue(
            should_delete_audio("until_approved", minutes_approved=True, recorded_at=rec, now=now)
        )

    def test_7d_and_14d_use_recording_age(self):
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        six = now - timedelta(days=6)
        eight = now - timedelta(days=8)
        thirteen = now - timedelta(days=13)
        fifteen = now - timedelta(days=15)
        self.assertFalse(should_delete_audio("7d", minutes_approved=False, recorded_at=six, now=now))
        self.assertTrue(should_delete_audio("7d", minutes_approved=False, recorded_at=eight, now=now))
        self.assertFalse(should_delete_audio("14d", minutes_approved=False, recorded_at=thirteen, now=now))
        self.assertTrue(should_delete_audio("14d", minutes_approved=False, recorded_at=fifteen, now=now))


class RetentionVaultTests(unittest.TestCase):
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

    def test_approve_deletes_wav_when_policy_until_approved(self):
        app_settings.save_settings({"retention": "until_approved", "setup_complete": True})
        meeting = vault.create_meeting({"title": "Regular Meeting", "organization": "SAL"})
        dest = vault.save_audio(meeting.id, b"RIFF____WAVEfmt ")
        self.assertTrue(dest.is_file())
        loaded = vault.load_meeting(meeting.id)
        self.assertTrue(loaded.has_audio)
        loaded.minutes_approved = True
        vault.save_meeting(loaded)
        self.assertFalse(vault.audio_path(loaded.id).is_file())
        again = vault.load_meeting(meeting.id)
        self.assertFalse(again.has_audio)
        self.assertTrue((config.vault_dir() / "meetings" / meeting.id / "minutes.md").is_file())

    def test_keep_leaves_wav_after_approve(self):
        app_settings.save_settings({"retention": "keep", "setup_complete": True})
        meeting = vault.create_meeting({"title": "Regular Meeting", "organization": "SAL"})
        vault.save_audio(meeting.id, b"RIFF____WAVEfmt ")
        loaded = vault.load_meeting(meeting.id)
        loaded.minutes_approved = True
        vault.save_meeting(loaded)
        self.assertTrue(vault.audio_path(loaded.id).is_file())


class TemplateTests(unittest.TestCase):
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

    def test_sal_create_includes_opening(self):
        app_settings.save_settings({"template": "sal", "setup_complete": True})
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        self.assertEqual(meeting.opening, SAL_OPENING)
        self.assertEqual(opening_for("notes"), [])


if __name__ == "__main__":
    unittest.main()
