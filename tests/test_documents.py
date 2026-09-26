"""Meeting document attach: vault file + meeting.json metadata."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from quorum import config, vault
from quorum.minutes import Meeting, MeetingDocument, normalize_doc_label
from quorum.server import Handler

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "quorum" / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "quorum" / "web" / "index.html").read_text(encoding="utf-8")


def _fn(source: str, name: str) -> str:
    marker = f"async function {name}"
    start = source.index(marker)
    nxt = re.search(r"\n(?:async )?function ", source[start + len(marker) :])
    return source[start : start + len(marker) + (nxt.start() if nxt else len(source))]


class DocumentLabelTests(unittest.TestCase):
    def test_known_labels_and_fallback(self):
        self.assertEqual(normalize_doc_label("Finance"), "finance")
        self.assertEqual(normalize_doc_label("agenda"), "agenda")
        self.assertEqual(normalize_doc_label("HANDOUT"), "handout")
        self.assertEqual(normalize_doc_label("other"), "other")
        self.assertEqual(normalize_doc_label("Bylaws"), "bylaws")
        self.assertEqual(normalize_doc_label("standing-rules"), "standing_rules")
        self.assertEqual(normalize_doc_label("prior_minutes"), "prior_minutes")
        self.assertEqual(normalize_doc_label("minutes"), "prior_minutes")
        self.assertEqual(normalize_doc_label("mystery"), "other")
        self.assertEqual(normalize_doc_label(""), "other")


class DocumentVaultTests(unittest.TestCase):
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

    def test_save_document_writes_file_and_metadata(self):
        meeting = vault.create_meeting({"title": "Regular Meeting", "organization": "SAL"})
        item = vault.save_document(meeting.id, b"%PDF-finance", filename="sheet.pdf", label="finance")
        dest = config.vault_dir() / "meetings" / meeting.id / "docs" / item.filename
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), b"%PDF-finance")
        self.assertEqual(item.label, "finance")
        self.assertEqual(item.filename, "sheet.pdf")
        self.assertEqual(item.bytes, len(b"%PDF-finance"))
        self.assertTrue(item.time)
        loaded = vault.load_meeting(meeting.id)
        self.assertEqual(len(loaded.documents), 1)
        self.assertIsInstance(loaded.documents[0], MeetingDocument)
        self.assertEqual(loaded.documents[0].label, "finance")
        raw = json.loads((config.vault_dir() / "meetings" / meeting.id / "meeting.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["documents"][0]["filename"], "sheet.pdf")
        self.assertEqual(raw["documents"][0]["bytes"], len(b"%PDF-finance"))

    def test_second_same_name_gets_unique_filename(self):
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        first = vault.save_document(meeting.id, b"one", filename="image.jpg", label="agenda")
        second = vault.save_document(meeting.id, b"two", filename="image.jpg", label="agenda")
        self.assertEqual(first.filename, "image.jpg")
        self.assertEqual(second.filename, "image_2.jpg")
        self.assertTrue((config.vault_dir() / "meetings" / meeting.id / "docs" / "image_2.jpg").is_file())

    def test_missing_meeting_errors(self):
        with self.assertRaises(FileNotFoundError):
            vault.save_document("no-such-meeting-id", b"hello", filename="x.txt")

    def test_invalid_meeting_id_errors(self):
        with self.assertRaises(ValueError):
            vault.save_document("../etc", b"hello", filename="x.txt")

    def test_empty_document_errors(self):
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        with self.assertRaises(ValueError):
            vault.save_document(meeting.id, b"", filename="empty.txt")

    def test_delete_meeting_removes_docs_dir(self):
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        vault.save_document(meeting.id, b"bye", filename="handout.txt", label="handout")
        folder = config.vault_dir() / "meetings" / meeting.id
        self.assertTrue((folder / "docs" / "handout.txt").is_file())
        vault.delete_meeting(meeting.id)
        self.assertFalse(folder.exists())

    def test_roundtrip_from_dict_keeps_documents(self):
        meeting = Meeting.from_dict(
            {
                "id": "abc-meeting",
                "documents": [
                    {"label": "finance", "filename": "a.jpg", "bytes": 4, "time": "2026-09-24T00:00:00+00:00"}
                ],
            }
        )
        self.assertEqual(meeting.documents[0].filename, "a.jpg")
        again = Meeting.from_dict(meeting.to_dict())
        self.assertEqual(again.documents[0].bytes, 4)


class DocumentHttpTests(unittest.TestCase):
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

    def test_upload_creates_file_and_metadata(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=finance&filename=sheet.jpg",
            raw=b"fake-jpeg",
        )
        self.assertEqual(uploaded["document"]["label"], "finance")
        self.assertEqual(uploaded["document"]["filename"], "sheet.jpg")
        self.assertEqual(uploaded["document"]["bytes"], len(b"fake-jpeg"))
        self.assertTrue(uploaded["document"]["time"])
        self.assertEqual(uploaded["meeting"]["documents"][0]["filename"], "sheet.jpg")
        dest = Path(os.environ["QUORUM_VAULT"]) / "meetings" / mid / "docs" / "sheet.jpg"
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), b"fake-jpeg")
        fetched = self._json("GET", f"/api/meetings/{mid}/documents/sheet.jpg")
        self.assertEqual(fetched, b"fake-jpeg")

    def test_unknown_meeting_is_error(self):
        missing = self._json(
            "POST",
            "/api/meetings/no-such-meeting-id/documents?filename=x.txt",
            raw=b"hello",
            code=404,
        )
        self.assertIn("error", missing)
        invalid = self._json(
            "POST",
            "/api/meetings/../x/documents?filename=x.txt",
            raw=b"hello",
            code=(400, 404),
        )
        self.assertIn("error", invalid)

    def test_empty_body_is_error(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        empty = self._json("POST", f"/api/meetings/{mid}/documents?filename=x.txt", raw=b"", code=400)
        self.assertIn("empty", empty["error"].lower())


class DocumentUiContractTests(unittest.TestCase):
    def test_console_has_camera_file_picker_label_and_list(self):
        for needle in (
            'id="doc-label"',
            'id="doc-photo"',
            'id="doc-file"',
            'id="doc-list"',
            'id="doc-label-reports"',
            'id="doc-list-reports"',
            'capture="environment"',
        ):
            self.assertIn(needle, INDEX)
        self.assertLess(INDEX.index('id="sign-in-photo"'), INDEX.index('id="doc-photo"'))
        self.assertLess(INDEX.index('id="report-list"'), INDEX.index('id="doc-list-reports"'))

    def test_claim_attached_only_after_api_ok(self):
        add = _fn(APP_JS, "addDocuments")
        self.assertIn("hasOpenMeeting()", add)
        self.assertIn("await api(`/api/meetings/${current.id}/documents", add)
        self.assertIn("Could not save document", add)
        self.assertLess(add.index("await api("), add.index("Attached"))
        self.assertLess(add.index("Attached"), add.index("} catch"))


if __name__ == "__main__":
    unittest.main()
