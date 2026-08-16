import tempfile
import unittest
from pathlib import Path

from quorum import backup, config, vault
from quorum.minutes import Meeting


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev_vault = config.os.environ.get("QUORUM_VAULT")
        self.prev_back = config.os.environ.get("QUORUM_BACKUPS")
        config.os.environ["QUORUM_VAULT"] = str(self.root / "vault")
        config.os.environ["QUORUM_BACKUPS"] = str(self.root / "backups")

    def tearDown(self):
        if self.prev_vault is None:
            config.os.environ.pop("QUORUM_VAULT", None)
        else:
            config.os.environ["QUORUM_VAULT"] = self.prev_vault
        if self.prev_back is None:
            config.os.environ.pop("QUORUM_BACKUPS", None)
        else:
            config.os.environ["QUORUM_BACKUPS"] = self.prev_back
        self.tmp.cleanup()

    def test_create_save_list_audio_backup(self):
        meeting = vault.create_meeting({"title": "Regular Meeting", "organization": "SAL"})
        self.assertTrue((config.vault_dir() / "meetings" / meeting.id / "meeting.json").is_file())
        loaded = vault.load_meeting(meeting.id)
        loaded.present = ["Mike"]
        vault.save_meeting(loaded)
        items = vault.list_meetings()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["organization"], "SAL")
        wav = b"RIFF____WAVEfmt "
        vault.save_audio(meeting.id, wav)
        self.assertTrue(vault.audio_path(meeting.id).is_file())
        dest = backup.make_backup()
        self.assertTrue(dest.is_file())
        self.assertGreater(dest.stat().st_size, 0)

    def test_roundtrip_nested(self):
        meeting = vault.create_meeting(
            {
                "new_business": [
                    {
                        "text": "buy lumber",
                        "mover": "Herm",
                        "seconder": "Mike",
                        "yeas": 8,
                        "nays": 0,
                        "result": "carried",
                    }
                ]
            }
        )
        again = vault.load_meeting(meeting.id)
        self.assertEqual(again.new_business[0].text, "buy lumber")
        self.assertIsInstance(again, Meeting)


if __name__ == "__main__":
    unittest.main()
