"""Bot: drive the real HTTP app through a full officer meeting."""

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

from quorum import config, gold
from quorum.server import Handler


class HttpBotTests(unittest.TestCase):
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

    def _json(self, method: str, path: str, payload=None, raw: bytes | None = None, code: int | tuple[int, ...] = 200):
        data = raw
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                allowed = code if isinstance(code, tuple) else (code,)
                self.assertIn(resp.status, allowed)
                if "json" in ctype:
                    return json.loads(body.decode("utf-8"))
                return body
        except HTTPError as exc:
            allowed = code if isinstance(code, tuple) else (code,)
            if exc.code in allowed:
                raw_err = exc.read()
                try:
                    return json.loads(raw_err.decode("utf-8"))
                except json.JSONDecodeError:
                    return raw_err
            raise

    def test_full_meeting_bot(self):
        health = self._json("GET", "/api/health")
        self.assertTrue(health["ok"])
        self.assertIn("Quorum", health["app"])

        page = self._json("GET", "/")
        html = page.decode("utf-8") if isinstance(page, bytes) else page
        for needle in ("Record", "meter", "Email minutes", "Dry-run", "Undo", "1st", "2nd"):
            self.assertIn(needle, html)

        settings = self._json(
            "POST",
            "/api/settings",
            {
                "setup_complete": True,
                "organization": "SAL Post 484 Squadron",
                "submitted_by": "Mike Featherstone",
                "submitted_office": "Adjutant, SAL Post 484",
                "template": "sal",
                "roberts": True,
                "retention": "until_approved",
                "roster": [
                    "Jeff Shumaker",
                    "Herm Clear",
                    "Mike Featherstone",
                    "Ted Ruser",
                    "William Wood",
                ],
            },
        )["settings"]
        self.assertEqual(settings["retention"], "until_approved")

        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        meeting = created["meeting"]
        mid = meeting["id"]
        self.assertTrue(meeting["date"])
        self.assertTrue(meeting["opening"])
        self.assertIn("SAL-Post-484", meeting["file_stem"])

        meeting["present"] = ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"]
        meeting["previous_minutes"] = "approved"
        meeting["reports"] = [
            {"title": "Finance", "presenter": "Ted Ruser", "body": "Checking ending $6,171.18"}
        ]
        meeting["new_business"] = [
            {
                "text": "SAL cover VA veterans meals",
                "mover": "William Wood",
                "seconder": "",
                "yeas": 0,
                "nays": 0,
                "result": "carried",
            }
        ]
        blocked = self._json("PUT", f"/api/meetings/{mid}", meeting, code=400)
        self.assertIn("second", blocked["error"].lower())

        meeting["new_business"][0]["seconder"] = "Herm Clear"
        meeting["new_business"][0]["yeas"] = 8
        meeting["new_business"][0]["result"] = "carried"
        meeting["adjournment"] = "With no further business, the meeting was adjourned."
        saved = self._json("PUT", f"/api/meetings/{mid}", meeting)
        self.assertEqual(saved["meeting"]["new_business"][0]["result"], "carried")
        self.assertTrue(gold.is_sal_shaped(saved["markdown"]), saved["markdown"])

        signed = self._json(
            "POST",
            f"/api/meetings/{mid}/signin",
            {"names": ["ted ruser", "Not On Roster"]},
        )
        self.assertIn("Ted Ruser", signed["meeting"]["present"])
        self.assertNotIn("Not On Roster", signed["meeting"]["present"])

        audio = self._json("POST", f"/api/meetings/{mid}/audio", raw=b"RIFF____WAVEfmt ")
        self.assertTrue(audio["ok"])
        wav = self._json("GET", f"/api/meetings/{mid}/audio")
        self.assertTrue(isinstance(wav, bytes) and wav.startswith(b"RIFF"))

        mail = self._json("GET", f"/api/meetings/{mid}/email")
        self.assertTrue(mail["subject"])
        self.assertIn("Meeting Minutes", mail["body"])
        self.assertIn("Herm Clear seconded", mail["body"])
        md = self._json("GET", f"/api/meetings/{mid}/minutes.md")
        self.assertIn(b"Roll Call / Quorum", md)
        printed = self._json("GET", f"/api/meetings/{mid}/print.html")
        self.assertIn(b"<!DOCTYPE html>", printed)

        saved["meeting"]["minutes_approved"] = True
        after = self._json("PUT", f"/api/meetings/{mid}", saved["meeting"])
        self.assertFalse(after["meeting"]["has_audio"])

        demo = self._json("POST", "/api/demo", {}, code=201)
        self.assertIn("Dry-run", demo["meeting"]["title"])
        self.assertTrue(demo["agenda"])

        bak = self._json("POST", "/api/backup", raw=b"", code=201)
        self.assertTrue(str(bak["name"]).endswith(".zip"))
        zipped = self._json("GET", f"/api/backups/{bak['name']}")
        self.assertTrue(isinstance(zipped, bytes) and zipped[:2] == b"PK")

        listed = self._json("GET", "/api/meetings")
        ids = {m["id"] for m in listed["meetings"]}
        self.assertIn(mid, ids)
        gone = self._json("DELETE", f"/api/meetings/{mid}")
        self.assertTrue(gone["ok"])


if __name__ == "__main__":
    unittest.main()
