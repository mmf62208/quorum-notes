"""Round C3 bylaws / standing-rules scan: extract, suggest, confirm, fallback."""

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

from quorum import bylaws, config, settings as app_settings, vault
from quorum.minutes import normalize_doc_label
from quorum.server import Handler
from quorum.settings import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "quorum" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bylaws"
BYLAWS_TXT = (FIXTURES / "cedar_grove_squadron_9.txt").read_text(encoding="utf-8")
BYLAWS_PDF = (FIXTURES / "cedar_grove_squadron_9.pdf").read_bytes()
BAD_SCAN = (FIXTURES / "bad_scan.jpg").read_bytes()
OLD_SETTINGS = Path(__file__).resolve().parent / "fixtures" / "old_settings.json"


def _fn(source: str, name: str) -> str:
    marker = f"async function {name}"
    start = source.index(marker)
    nxt = re.search(r"\n(?:async )?function ", source[start + len(marker) :])
    return source[start : start + len(marker) + (nxt.start() if nxt else len(source))]


class BylawsExtractTests(unittest.TestCase):
    def test_quorum_sentence_from_text(self):
        sentences = bylaws.extract_quorum_sentences(BYLAWS_TXT)
        self.assertTrue(sentences)
        self.assertTrue(any("quorum shall consist" in row.casefold() for row in sentences))
        self.assertTrue(any("three other officers" in row.casefold() for row in sentences))

    def test_officer_titles_from_text(self):
        titles = bylaws.extract_officer_titles(BYLAWS_TXT)
        for wanted in (
            "Commander",
            "1st Vice Commander",
            "2nd Vice Commander",
            "Adjutant",
            "Finance Officer",
            "Chaplain",
            "Sergeant-at-Arms",
            "Historian",
        ):
            self.assertIn(wanted, titles)
        self.assertNotIn("Member", titles)

    def test_customs_from_text(self):
        customs = bylaws.extract_customs(BYLAWS_TXT)
        topics = {row["topic"] for row in customs}
        texts = " ".join(row["text"] for row in customs).casefold()
        self.assertIn("meeting_day", topics)
        self.assertIn("order_of_business", topics)
        self.assertIn("opening", topics)
        self.assertIn("second tuesday", texts)
        self.assertIn("7:00 p.m", texts)
        self.assertIn("order of business", texts)
        self.assertIn("opening ceremon", texts)

    def test_pdf_like_text_extracts_same_items(self):
        scan = bylaws.scan_bytes(BYLAWS_PDF, filename="cedar_grove_squadron_9.pdf", label="bylaws")
        self.assertEqual(scan.extractor, "pdf-text")
        self.assertTrue(scan.found)
        self.assertTrue(scan.quorum)
        self.assertTrue(scan.officers)
        self.assertTrue(scan.customs)
        self.assertIn("Suggestions only", scan.message)

    def test_text_file_scan(self):
        scan = bylaws.scan_bytes(
            BYLAWS_TXT.encode("utf-8"),
            filename="cedar_grove_squadron_9.txt",
            label="standing_rules",
        )
        self.assertEqual(scan.extractor, "text")
        self.assertEqual(scan.label, "standing_rules")
        self.assertTrue(scan.quorum)
        self.assertEqual(scan.quorum[0]["kind"], "quorum")
        self.assertIn("quorum", scan.quorum[0]["text"].casefold())

    def test_suggested_rule_prefers_structured_when_titles_and_count(self):
        sentence = "A quorum shall consist of the Commander or a Vice Commander and three other officers."
        rule = bylaws.suggested_quorum_rule(sentence)
        self.assertEqual(rule.mode, "structured")
        self.assertGreaterEqual(len(rule.presiding_any_of), 1)
        self.assertEqual(rule.min_other_officers, 3)
        self.assertEqual(rule.notes, sentence)

    def test_bad_scan_finds_nothing(self):
        scan = bylaws.scan_bytes(BAD_SCAN, filename="bad_scan.jpg", label="bylaws")
        self.assertFalse(scan.found)
        self.assertFalse(scan.quorum)
        self.assertFalse(scan.officers)
        self.assertIn("kept in the vault", scan.message.casefold())

    def test_ocr_tool_absent_path(self):
        prev = bylaws._on_path

        def missing(_name: str):
            return None

        bylaws._on_path = missing
        try:
            extracted = bylaws.extract_text(BAD_SCAN, filename="page.jpg")
            self.assertEqual(extracted.extractor, "none")
            self.assertIn("tesseract", extracted.tools_missing)
            scan = bylaws.scan_bytes(BAD_SCAN, filename="page.jpg", label="bylaws")
            self.assertFalse(scan.found)
            self.assertIn("tesseract", scan.message.casefold())
            self.assertIn("kept in the vault", scan.message.casefold())
            self.assertFalse(bylaws.local_tools()["tesseract"])
            self.assertFalse(bylaws.local_tools()["pdftotext"])
        finally:
            bylaws._on_path = prev


class BylawsApplyTests(unittest.TestCase):
    def test_scan_does_not_apply(self):
        settings = {
            "quorum_rule": {"mode": "none"},
            "officers": [{"role": "Commander", "name": "Pat Hale"}],
        }
        scan = bylaws.scan_text(BYLAWS_TXT, filename="bylaws.txt", settings=settings)
        self.assertTrue(scan.found)
        self.assertEqual(settings["officers"][0]["name"], "Pat Hale")
        self.assertEqual(settings["quorum_rule"]["mode"], "none")
        plan = bylaws.plan_apply(settings, {})
        self.assertEqual(plan.update, {})
        self.assertEqual(plan.applied, [])

    def test_confirm_fills_quorum_and_officers(self):
        settings = {"quorum_rule": {"mode": "none"}, "officers": []}
        scan = bylaws.scan_text(BYLAWS_TXT, filename="bylaws.txt", settings=settings)
        plan = bylaws.plan_apply(
            settings,
            {
                "quorum": {"confirm": True, "text": scan.quorum[0]["text"], "rule": scan.quorum[0]["rule"]},
                "officers": [
                    {"confirm": True, "title": "Adjutant"},
                    {"confirm": True, "title": "Chaplain"},
                ],
            },
        )
        self.assertIn("quorum_rule", plan.update)
        self.assertEqual(plan.update["quorum_rule"]["mode"], "structured")
        self.assertIn("A quorum shall consist", plan.update["quorum_rule"]["notes"])
        roles = {row["role"] for row in plan.update["officers"]}
        self.assertIn("Adjutant", roles)
        self.assertIn("Chaplain", roles)
        self.assertTrue(all(row["name"] == "" for row in plan.update["officers"] if row["role"] in roles))

    def test_no_overwrite_without_confirm(self):
        settings = {
            "quorum_rule": {
                "mode": "text",
                "notes": "Existing rule stays until confirmed.",
            },
            "officers": [{"role": "Commander", "name": "Pat Hale"}],
        }
        scan = bylaws.scan_text(BYLAWS_TXT, filename="bylaws.txt", settings=settings)
        self.assertTrue(scan.quorum[0]["would_overwrite"])
        commander = next(row for row in scan.officers if row["title"] == "Commander")
        self.assertTrue(commander["would_overwrite"])
        self.assertIn("Pat Hale", commander["change"])
        plan = bylaws.plan_apply(
            settings,
            {
                "quorum": {"confirm": True, "overwrite": False, "text": scan.quorum[0]["text"]},
                "officers": [{"confirm": True, "overwrite": False, "title": "Commander"}],
            },
        )
        self.assertNotIn("quorum_rule", plan.update)
        self.assertNotIn("officers", plan.update)
        self.assertTrue(any(row["kind"] == "quorum" and row["reason"] == "exists" for row in plan.skipped))
        self.assertTrue(any(row["kind"] == "officer" and row["reason"] == "exists" for row in plan.skipped))

    def test_overwrite_quorum_with_explicit_confirm(self):
        settings = {"quorum_rule": {"mode": "text", "notes": "Old wording."}}
        sentence = "A quorum shall consist of the Commander or a Vice Commander and three other officers."
        plan = bylaws.plan_apply(
            settings,
            {"quorum": {"confirm": True, "overwrite": True, "text": sentence}},
        )
        self.assertEqual(plan.update["quorum_rule"]["notes"], sentence)
        self.assertTrue(plan.applied[0]["overwrote"])

    def test_customs_are_readonly_and_not_applied(self):
        scan = bylaws.scan_text(BYLAWS_TXT, filename="bylaws.txt")
        self.assertTrue(scan.customs)
        self.assertTrue(all(row["readonly"] for row in scan.customs))
        plan = bylaws.plan_apply({"quorum_rule": {"mode": "none"}}, {"customs": scan.customs})
        self.assertEqual(plan.update, {})


class BylawsVaultHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.prev = {
            "QUORUM_VAULT": os.environ.get("QUORUM_VAULT"),
            "QUORUM_BACKUPS": os.environ.get("QUORUM_BACKUPS"),
        }
        os.environ["QUORUM_VAULT"] = str(root / "vault")
        os.environ["QUORUM_BACKUPS"] = str(root / "backups")

    def tearDown(self):
        for key, value in self.prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_failure_fallback_keeps_file(self):
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        item = vault.save_document(meeting.id, BAD_SCAN, filename="bad_scan.jpg", label="bylaws")
        dest = config.vault_dir() / "meetings" / meeting.id / "docs" / item.filename
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), BAD_SCAN)
        scan = bylaws.scan_bytes(BAD_SCAN, filename=item.filename, label=item.label)
        self.assertFalse(scan.found)
        prefs = app_settings.load_settings()
        self.assertNotIn("quorum_rule", prefs)
        loaded = vault.load_meeting(meeting.id)
        self.assertEqual(loaded.documents[0].filename, item.filename)

    def test_old_vault_settings_still_load(self):
        dest = config.vault_dir()
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "settings.json").write_text(OLD_SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
        loaded = app_settings.load_settings()
        self.assertEqual(loaded["organization"], json.loads(OLD_SETTINGS.read_text(encoding="utf-8"))["organization"])
        scan = bylaws.scan_text(BYLAWS_TXT, settings=loaded)
        self.assertTrue(scan.found)
        plan = bylaws.plan_apply(loaded, {})
        self.assertEqual(plan.update, {})


class BylawsHttpTests(unittest.TestCase):
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

    def setUp(self):
        dest = Path(os.environ["QUORUM_VAULT"])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "settings.json").write_text(json.dumps(dict(DEFAULTS), indent=2) + "\n", encoding="utf-8")

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

    def test_upload_returns_suggestions_without_saving_rule(self):
        self._json(
            "POST",
            "/api/settings",
            {"setup_complete": True, "organization": "Cedar Grove Squadron 9", "roster": ["Member A"]},
        )
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=bylaws&filename=cedar.txt",
            raw=BYLAWS_TXT.encode("utf-8"),
        )
        self.assertEqual(uploaded["document"]["label"], "bylaws")
        dest = Path(os.environ["QUORUM_VAULT"]) / "meetings" / mid / "docs" / "cedar.txt"
        self.assertTrue(dest.is_file())
        scan = uploaded["bylaws_scan"]
        self.assertTrue(scan["found"])
        self.assertTrue(scan["quorum"])
        prefs = self._json("GET", "/api/settings")["settings"]
        self.assertNotIn("quorum_rule", prefs)
        self.assertNotIn("officers", prefs)

    def test_confirm_fills_settings(self):
        self._json("POST", "/api/settings", {"setup_complete": True, "organization": "Cedar Grove Squadron 9"})
        scanned = self._json("POST", "/api/bylaws/scan", {"text": BYLAWS_TXT, "filename": "cedar.txt"})
        scan = scanned["bylaws_scan"]
        confirmed = self._json(
            "POST",
            "/api/bylaws/confirm",
            {
                "quorum": {"confirm": True, "text": scan["quorum"][0]["text"], "rule": scan["quorum"][0]["rule"]},
                "officers": [{"confirm": True, "title": "Historian"}],
            },
        )
        self.assertEqual(confirmed["settings"]["quorum_rule"]["mode"], "structured")
        self.assertIn("Historian", [row["role"] for row in confirmed["settings"]["officers"]])
        self.assertEqual(next(row for row in confirmed["settings"]["officers"] if row["role"] == "Historian")["name"], "")

    def test_confirm_refuses_overwrite_without_flag(self):
        self._json(
            "POST",
            "/api/settings",
            {
                "quorum_rule": {"mode": "text", "notes": "Leave this."},
                "officers": [{"role": "Commander", "name": "Pat Hale"}],
            },
        )
        blocked = self._json(
            "POST",
            "/api/bylaws/confirm",
            {
                "quorum": {"confirm": True, "overwrite": False, "text": "A quorum shall consist of ten members."},
                "officers": [{"confirm": True, "overwrite": False, "title": "Commander"}],
            },
        )
        self.assertEqual(blocked["settings"]["quorum_rule"]["notes"], "Leave this.")
        self.assertEqual(blocked["settings"]["officers"][0]["name"], "Pat Hale")
        self.assertEqual(blocked["applied"], [])

    def test_bad_scan_upload_keeps_file(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=standing_rules&filename=bad_scan.jpg",
            raw=BAD_SCAN,
        )
        self.assertEqual(uploaded["document"]["label"], "standing_rules")
        self.assertFalse(uploaded["bylaws_scan"]["found"])
        self.assertTrue(
            (Path(os.environ["QUORUM_VAULT"]) / "meetings" / mid / "docs" / "bad_scan.jpg").is_file()
        )

    def test_finance_upload_has_no_scan(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=finance&filename=sheet.jpg",
            raw=b"sheet-bytes",
        )
        self.assertNotIn("bylaws_scan", uploaded)


class BylawsUiContractTests(unittest.TestCase):
    def test_labels_and_review_list(self):
        for needle in (
            'value="bylaws"',
            'value="standing_rules"',
            'id="bylaws-review"',
            'id="bylaws-suggestions"',
            'id="btn-bylaws-confirm"',
            "Confirm selected",
            "Open quorum rule",
            "Open officers",
        ):
            self.assertIn(needle, INDEX)
        self.assertIn(">Bylaws<", INDEX)
        self.assertIn("Standing rules", INDEX)
        self.assertLess(INDEX.index('id="btn-rec"'), INDEX.index('id="bylaws-review"'))

    def test_record_still_available(self):
        self.assertIn('id="btn-rec"', INDEX)
        self.assertIn("Record", INDEX)
        start = APP_JS[APP_JS.index("async function startRec") : APP_JS.index("async function startRec") + 500]
        self.assertIn("hasOpenMeeting()", start)
        self.assertNotIn("bylaws", start)

    def test_suggestions_not_auto_applied_in_js(self):
        add = _fn(APP_JS, "addDocuments")
        self.assertIn("bylaws_scan", add)
        self.assertNotIn("/api/bylaws/confirm", add)
        self.assertNotIn("/api/settings", add)
        self.assertIn("showBylawsScan", add)
        confirm = _fn(APP_JS, "confirmBylawsSelected")
        self.assertIn("/api/bylaws/confirm", confirm)
        self.assertIn("fillWizardQuorum", confirm)

    def test_doc_label_normalizes_rules(self):
        self.assertEqual(normalize_doc_label("Bylaws"), "bylaws")
        self.assertEqual(normalize_doc_label("standing-rules"), "standing_rules")
        self.assertEqual(normalize_doc_label("Standing rules"), "standing_rules")
        self.assertEqual(normalize_doc_label("mystery"), "other")


if __name__ == "__main__":
    unittest.main()
