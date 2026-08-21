"""Pack zip for testers: launchers, docs, no shipped real roster."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABSENT = Path(__file__).with_name("absent_shipped_names.txt")


class PackTesterTests(unittest.TestCase):
    def test_zip_has_launch_docs_demo_and_omits_real_roster(self):
        dest = Path(tempfile.mkdtemp()) / "quorum-tester.zip"
        subprocess.check_call(["/bin/sh", str(ROOT / "tools" / "pack_tester.sh"), str(dest)])
        self.assertTrue(dest.is_file())
        names = [line.strip() for line in ABSENT.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(names)
        with zipfile.ZipFile(dest) as zf:
            members = zf.namelist()
            self.assertTrue(any("Start Quorum" in name for name in members), members)
            self.assertTrue(any(name.endswith("docs/OFFICER.md") for name in members), members)
            self.assertTrue(any(name.endswith("quorum/demo.py") for name in members), members)
            tops = {name.split("/", 1)[0] for name in members if name}
            self.assertEqual(tops, {"quorum-notes"})
            blob = b"".join(zf.read(name) for name in members)
            text = blob.decode("utf-8", errors="replace")
            for name in names:
                self.assertNotIn(name, text)


if __name__ == "__main__":
    unittest.main()
