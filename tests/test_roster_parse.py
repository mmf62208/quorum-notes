"""Flexible roster paste: each shape, garbage, and no invented present names."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from quorum import config, roster, vault
from quorum.server import Handler

WEB = Path(__file__).resolve().parents[1] / "quorum" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


class RosterParseShapeTests(unittest.TestCase):
    def test_title_colon_name(self):
        result = roster.parse_roster("Commander: Jeff Shumaker\nChaplain:Herm Clear")
        self.assertEqual(result["names"], ["Jeff Shumaker", "Herm Clear"])
        self.assertEqual(result["entries"][0]["title"], "Commander")
        self.assertEqual(result["entries"][1]["title"], "Chaplain")

    def test_title_dash_name(self):
        result = roster.parse_roster("Adjutant - Mike Featherstone\nFinance Officer — Ted Ruser")
        self.assertEqual(result["names"], ["Mike Featherstone", "Ted Ruser"])
        self.assertEqual(result["entries"][0]["title"], "Adjutant")
        self.assertEqual(result["entries"][1]["title"], "Finance Officer")

    def test_name_comma_title(self):
        result = roster.parse_roster("William Wood, Sergeant-at-Arms")
        self.assertEqual(result["names"], ["William Wood"])
        self.assertEqual(result["entries"][0]["title"], "Sergeant-at-Arms")

    def test_name_then_known_title(self):
        result = roster.parse_roster("Herm Clear Chaplain\nMike Featherstone Adjutant")
        self.assertEqual(result["names"], ["Herm Clear", "Mike Featherstone"])
        self.assertEqual(result["entries"][0]["title"], "Chaplain")
        self.assertEqual(result["entries"][1]["title"], "Adjutant")

    def test_known_title_then_name(self):
        result = roster.parse_roster("Commander Jeff Shumaker")
        self.assertEqual(result["names"], ["Jeff Shumaker"])
        self.assertEqual(result["entries"][0]["title"], "Commander")

    def test_csv_name_title_with_header(self):
        text = "name,title\nJeff Shumaker,Commander\nHerm Clear,Chaplain"
        result = roster.parse_roster(text)
        self.assertEqual(result["names"], ["Jeff Shumaker", "Herm Clear"])
        self.assertEqual(result["entries"][0]["title"], "Commander")

    def test_csv_title_name_with_header(self):
        text = "title,name\nCommander,Jeff Shumaker\nAdjutant,Mike Featherstone"
        result = roster.parse_roster(text)
        self.assertEqual(result["names"], ["Jeff Shumaker", "Mike Featherstone"])
        self.assertEqual(result["entries"][1]["title"], "Adjutant")

    def test_csv_without_header_detects_order(self):
        text = "Commander,Jeff Shumaker\nWilliam Wood,Historian"
        result = roster.parse_roster(text)
        self.assertEqual(result["names"], ["Jeff Shumaker", "William Wood"])
        self.assertEqual(result["entries"][0]["title"], "Commander")
        self.assertEqual(result["entries"][1]["title"], "Historian")

    def test_tsv_name_title(self):
        text = "name\ttitle\nTed Ruser\tFinance Officer"
        result = roster.parse_roster(text)
        self.assertEqual(result["names"], ["Ted Ruser"])
        self.assertEqual(result["entries"][0]["title"], "Finance Officer")

    def test_plain_one_name_per_line_still_works(self):
        result = roster.parse_roster("Jeff Shumaker\nHerm Clear\nMike Featherstone")
        self.assertEqual(result["names"], ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"])
        self.assertTrue(all(e["title"] == "" for e in result["entries"]))

    def test_mixed_shapes_in_one_paste(self):
        text = "\n".join(
            [
                "Commander: Jeff Shumaker",
                "Herm Clear, Chaplain",
                "Mike Featherstone Adjutant",
                "Ted Ruser",
                "Finance Officer - William Wood",
            ]
        )
        result = roster.parse_roster(text)
        self.assertEqual(
            result["names"],
            ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser", "William Wood"],
        )

    def test_garbage_lines_skipped_or_flagged(self):
        text = "\n".join(
            [
                "Commander: Jeff Shumaker",
                "---",
                "n/a",
                "???",
                "Phone: 555-0100",
                "https://example.com",
                "present",
                "12345",
                "Herm Clear",
            ]
        )
        result = roster.parse_roster(text)
        self.assertEqual(result["names"], ["Jeff Shumaker", "Herm Clear"])
        skipped_lines = [row["line"] for row in result["skipped"]]
        self.assertIn("---", skipped_lines)
        self.assertIn("n/a", skipped_lines)
        self.assertIn("Phone: 555-0100", skipped_lines)
        self.assertIn("https://example.com", skipped_lines)
        self.assertIn("present", skipped_lines)
        self.assertIn("12345", skipped_lines)

    def test_duplicates_flagged(self):
        result = roster.parse_roster("Jeff Shumaker\ncommander: jeff shumaker")
        self.assertEqual(result["names"], ["Jeff Shumaker"])
        self.assertTrue(any(row["reason"] == "duplicate" for row in result["skipped"]))

    def test_parse_does_not_imply_present(self):
        result = roster.parse_roster("Commander: Jeff Shumaker\nUnknown Guest")
        self.assertNotIn("present", result)
        self.assertEqual(set(result.keys()), {"entries", "skipped", "names"})


class RosterParseHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.prev = {
            "QUORUM_VAULT": os.environ.get("QUORUM_VAULT"),
            "QUORUM_BACKUPS": os.environ.get("QUORUM_BACKUPS"),
        }
        os.environ["QUORUM_VAULT"] = str(root / "vault")
        os.environ["QUORUM_BACKUPS"] = str(root / "backups")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for key, value in cls.prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.tmp.cleanup()

    def _json(self, method: str, path: str, payload=None, code: int = 200):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req) as resp:
                self.assertEqual(resp.status, code)
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == code:
                return json.loads(exc.read().decode("utf-8"))
            raise

    def test_parse_endpoint_preview_only(self):
        before = self._json("GET", "/api/meetings")
        parsed = self._json(
            "POST",
            "/api/roster/parse",
            {"text": "Commander: Jeff Shumaker\nn/a\nHerm Clear, Chaplain"},
        )
        self.assertEqual(parsed["names"], ["Jeff Shumaker", "Herm Clear"])
        self.assertTrue(parsed["skipped"])
        after = self._json("GET", "/api/meetings")
        self.assertEqual(after["meetings"], before["meetings"])

    def test_apply_roster_does_not_mark_present(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting", "roster": []}, code=201)
        mid = created["meeting"]["id"]
        self.assertEqual(created["meeting"]["present"], [])
        applied = self._json(
            "POST",
            f"/api/meetings/{mid}/roster",
            {"names": ["Jeff Shumaker", "Herm Clear"]},
        )
        self.assertEqual(applied["meeting"]["roster"], ["Jeff Shumaker", "Herm Clear"])
        self.assertEqual(applied["meeting"]["present"], [])
        loaded = vault.load_meeting(mid)
        self.assertEqual(loaded.present, [])
        self.assertEqual(loaded.roster, ["Jeff Shumaker", "Herm Clear"])


class RosterConfirmUiContractTests(unittest.TestCase):
    def test_wizard_and_meeting_have_confirm_list(self):
        for needle in (
            'id="wiz-roster"',
            'id="wiz-roster-confirm"',
            'id="btn-wiz-roster-add"',
            'id="meet-roster-paste"',
            'id="meet-roster-confirm"',
            'id="btn-apply-roster"',
        ):
            self.assertIn(needle, INDEX)
        self.assertLess(INDEX.index('id="wiz-roster"'), INDEX.index('id="wiz-roster-confirm"'))
        self.assertLess(INDEX.index('id="wiz-roster-confirm"'), INDEX.index('id="btn-wiz-save"'))
        self.assertLess(INDEX.index('id="meet-roster-confirm"'), INDEX.index('id="btn-apply-roster"'))

    def test_apply_paths_do_not_write_present(self):
        self.assertIn("/api/roster/parse", APP_JS)
        self.assertIn("/api/meetings/${current.id}/roster", APP_JS)
        apply_at = APP_JS.index("btn-apply-roster")
        chunk = APP_JS[apply_at : apply_at + 800]
        self.assertNotIn("present.push", chunk)
        self.assertNotIn("current.present =", chunk)
        save_at = APP_JS.index("btn-wiz-save")
        save_chunk = APP_JS[save_at : save_at + 900]
        self.assertIn("confirmedRosterNames", save_chunk)
        self.assertNotIn("present:", save_chunk)


if __name__ == "__main__":
    unittest.main()
