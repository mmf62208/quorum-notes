"""Round C2 prior-minutes style import: cues, suggestions, confirm, preview, fallback."""

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

from quorum import config, prior_minutes, settings as app_settings, vault
from quorum.minutes import (
    Meeting,
    Motion,
    apply_minutes_style,
    minutes_style_from,
    normalize_doc_label,
    render_minutes,
)
from quorum.server import Handler
from quorum.settings import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "quorum" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "prior_minutes"
HOUSE = (FIXTURES / "house_style.txt").read_text(encoding="utf-8")
MOTION_BY = (FIXTURES / "motion_by_full_names.txt").read_text(encoding="utf-8")
MOTION_BY_PDF = (FIXTURES / "motion_by_full_names.pdf").read_bytes()
BAD_SCAN = (FIXTURES / "bad_scan.jpg").read_bytes()
OLD_SETTINGS = Path(__file__).resolve().parent / "fixtures" / "old_settings.json"


def _fn(source: str, name: str) -> str:
    marker = f"async function {name}"
    start = source.index(marker)
    nxt = re.search(r"\n(?:async )?function ", source[start + len(marker) :])
    return source[start : start + len(marker) + (nxt.start() if nxt else len(source))]


def _preview_meeting() -> Meeting:
    return Meeting(
        id="c2-preview",
        title="Regular Meeting",
        organization="Example Squadron 12",
        date="September 22, 2026",
        called_to_order_by="Commander Pat Hale",
        roster=["Pat Hale", "Herm Walsh", "Randy Cole", "Mike Foster"],
        present=["Pat Hale", "Herm Walsh", "Randy Cole", "Mike Foster"],
        new_business=[
            Motion(
                text="accept the financial report as presented",
                mover="Herm Walsh",
                seconder="Randy Cole",
                yeas=4,
                nays=0,
                result="carried",
            )
        ],
        submitted_by="Mike Foster",
        submitted_office="Adjutant",
        minutes_closing="For God and Country",
        notes="Hand-edited scratch notes stay put.",
    )


class PriorCueTests(unittest.TestCase):
    def test_house_style_cues(self):
        cues = prior_minutes.detect_cues(HOUSE)
        self.assertEqual(cues.motion_phrasing, "moved_seconded")
        self.assertEqual(cues.name_style, "first")
        self.assertEqual(cues.signature_shape, "respectfully")
        self.assertEqual(cues.closing, "For God and Country")
        self.assertIn("called_to_order", cues.heading_order)
        self.assertIn("old_business", cues.heading_order)
        self.assertIn("new_business", cues.heading_order)
        self.assertLess(cues.heading_order.index("old_business"), cues.heading_order.index("new_business"))
        self.assertTrue(any("no new motion" in item.casefold() for item in cues.old_business))
        self.assertTrue(any("postponed" in item.casefold() for item in cues.old_business))

    def test_motion_by_full_name_cues(self):
        cues = prior_minutes.detect_cues(MOTION_BY)
        self.assertEqual(cues.motion_phrasing, "motion_by")
        self.assertEqual(cues.name_style, "full")
        self.assertEqual(cues.signature_shape, "submitted_by_line")
        self.assertEqual(cues.closing, "In service to the community")
        self.assertTrue(cues.motion_pairs)
        self.assertTrue(any(len(mover.split()) >= 2 for mover, _second in cues.motion_pairs))
        carried = " ".join(cues.old_business).casefold()
        self.assertIn("tabled", carried)
        self.assertIn("follow up", carried)

    def test_pdf_reuses_c3_extract(self):
        scan = prior_minutes.scan_bytes(
            MOTION_BY_PDF,
            filename="motion_by_full_names.pdf",
            label="prior_minutes",
        )
        self.assertEqual(scan.extractor, "pdf-text")
        self.assertTrue(scan.found)
        fields = {row["field"] for row in scan.style}
        self.assertIn("minutes_motion_phrasing", fields)
        self.assertEqual(
            next(row for row in scan.style if row["field"] == "minutes_motion_phrasing")["value"],
            "motion_by",
        )

    def test_text_file_scan(self):
        scan = prior_minutes.scan_bytes(
            HOUSE.encode("utf-8"),
            filename="house_style.txt",
            label="minutes",
        )
        self.assertEqual(scan.extractor, "text")
        self.assertEqual(scan.label, "prior_minutes")
        self.assertTrue(scan.style)
        self.assertTrue(scan.old_business)
        self.assertIn("Suggestions only", scan.message)

    def test_bad_scan_finds_nothing(self):
        scan = prior_minutes.scan_bytes(BAD_SCAN, filename="bad_scan.jpg", label="prior_minutes")
        self.assertFalse(scan.found)
        self.assertFalse(scan.style)
        self.assertFalse(scan.old_business)
        self.assertIn("kept in the vault", scan.message.casefold())


class PriorApplyTests(unittest.TestCase):
    def test_scan_does_not_apply(self):
        settings = {"minutes_closing": "Existing closing"}
        meeting = Meeting(id="keep", old_business=["Already here"], notes="Do not clobber")
        scan = prior_minutes.scan_text(HOUSE, filename="house.txt", settings=settings, meeting=meeting)
        self.assertTrue(scan.found)
        self.assertEqual(settings["minutes_closing"], "Existing closing")
        self.assertEqual(meeting.old_business, ["Already here"])
        self.assertEqual(meeting.notes, "Do not clobber")
        plan = prior_minutes.plan_apply(settings, {}, meeting)
        self.assertEqual(plan.update, {})
        self.assertEqual(plan.applied, [])
        self.assertEqual(plan.old_business, ["Already here"])

    def test_confirm_updates_style_and_render(self):
        settings = {}
        scan = prior_minutes.scan_text(MOTION_BY, filename="motion.txt", settings=settings)
        style_payload = [
            {
                "confirm": True,
                "field": row["field"],
                "value": row["value"],
                "overwrite": True,
            }
            for row in scan.style
        ]
        plan = prior_minutes.plan_apply(settings, {"style": style_payload})
        self.assertEqual(plan.update.get("minutes_motion_phrasing"), "motion_by")
        self.assertEqual(plan.update.get("minutes_name_style"), "full")
        self.assertEqual(plan.update.get("minutes_signature_shape"), "submitted_by_line")
        self.assertEqual(plan.update.get("minutes_closing"), "In service to the community")
        meeting = _preview_meeting()
        before = render_minutes(meeting)
        apply_minutes_style(meeting, minutes_style_from(plan.update))
        after = render_minutes(meeting)
        self.assertIn("Herm moved to accept the financial report as presented; Randy seconded.", before)
        self.assertIn("Motion by Herm Walsh, seconded by Randy Cole, to accept the financial report as presented.", after)
        self.assertIn("**Respectfully submitted,**", before)
        self.assertIn("**Submitted by Mike Foster, Adjutant, Example Squadron 12.**", after)
        self.assertIn("**In service to the community**", after)
        self.assertNotIn("Herm moved", after)

    def test_preview_before_after(self):
        settings = {}
        scan = prior_minutes.scan_text(
            MOTION_BY,
            filename="motion.txt",
            settings=settings,
            meeting=_preview_meeting(),
        )
        self.assertTrue(scan.preview["before"])
        self.assertTrue(scan.preview["after"])
        self.assertNotEqual(scan.preview["before"], scan.preview["after"])
        self.assertIn("Herm moved", scan.preview["before"])
        self.assertIn("Motion by Herm Walsh, seconded by Randy Cole", scan.preview["after"])

    def test_carry_old_business_confirm_required(self):
        meeting = Meeting(id="carry", old_business=[], notes="Keep me")
        scan = prior_minutes.scan_text(HOUSE, filename="house.txt", meeting=meeting)
        self.assertTrue(scan.old_business)
        plan = prior_minutes.plan_apply({}, {"old_business": scan.old_business}, meeting)
        self.assertEqual(plan.old_business, [])
        self.assertFalse(any(row["kind"] == "old_business" for row in plan.applied))
        confirmed = [{"confirm": True, "text": row["text"]} for row in scan.old_business]
        plan = prior_minutes.plan_apply({}, {"old_business": confirmed}, meeting)
        self.assertGreaterEqual(len(plan.old_business), 2)
        self.assertTrue(any("no new motion" in item.casefold() for item in plan.old_business))
        self.assertEqual(meeting.notes, "Keep me")
        self.assertEqual(meeting.old_business, [])

    def test_no_overwrite_without_flag(self):
        settings = {"minutes_closing": "Leave this."}
        plan = prior_minutes.plan_apply(
            settings,
            {"style": [{"confirm": True, "overwrite": False, "field": "minutes_closing", "value": "For God and Country"}]},
        )
        self.assertNotIn("minutes_closing", plan.update)
        self.assertTrue(any(row["reason"] == "exists" for row in plan.skipped))

    def test_overwrite_closing_with_explicit_confirm(self):
        settings = {"minutes_closing": "Leave this."}
        plan = prior_minutes.plan_apply(
            settings,
            {"style": [{"confirm": True, "overwrite": True, "field": "minutes_closing", "value": "For God and Country"}]},
        )
        self.assertEqual(plan.update["minutes_closing"], "For God and Country")
        self.assertTrue(plan.applied[0]["overwrote"])


class PriorVaultHttpTests(unittest.TestCase):
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
        item = vault.save_document(meeting.id, BAD_SCAN, filename="bad_scan.jpg", label="prior_minutes")
        dest = config.vault_dir() / "meetings" / meeting.id / "docs" / item.filename
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), BAD_SCAN)
        scan = prior_minutes.scan_bytes(BAD_SCAN, filename=item.filename, label=item.label)
        self.assertFalse(scan.found)
        prefs = app_settings.load_settings()
        self.assertNotIn("minutes_motion_phrasing", prefs)
        loaded = vault.load_meeting(meeting.id)
        self.assertEqual(loaded.documents[0].filename, item.filename)
        self.assertEqual(loaded.old_business, [])

    def test_old_vault_settings_still_load(self):
        dest = config.vault_dir()
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "settings.json").write_text(OLD_SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
        loaded = app_settings.load_settings()
        self.assertEqual(loaded["organization"], json.loads(OLD_SETTINGS.read_text(encoding="utf-8"))["organization"])
        self.assertNotIn("minutes_name_style", loaded)
        scan = prior_minutes.scan_text(HOUSE, settings=loaded)
        self.assertTrue(scan.found)
        plan = prior_minutes.plan_apply(loaded, {})
        self.assertEqual(plan.update, {})

    def test_confirm_writes_settings_and_old_business(self):
        app_settings.save_settings({"setup_complete": True, "organization": "Example Squadron 12"})
        meeting = vault.create_meeting({"title": "Regular Meeting", "notes": "Hand edit"})
        meeting.new_business = [
            Motion(text="accept the report", mover="Herm Walsh", seconder="Randy Cole", result="carried")
        ]
        meeting.submitted_by = "Mike Foster"
        vault.save_meeting(meeting)
        scan = prior_minutes.scan_text(MOTION_BY, filename="motion.txt", meeting=meeting)
        plan = prior_minutes.apply_confirmed(
            app_settings.load_settings(),
            {
                "style": [
                    {"confirm": True, "field": row["field"], "value": row["value"], "overwrite": True}
                    for row in scan.style
                ],
                "old_business": [{"confirm": True, "text": row["text"]} for row in scan.old_business],
                "meeting_id": meeting.id,
            },
            meeting,
        )
        self.assertEqual(plan.settings["minutes_motion_phrasing"], "motion_by")
        self.assertTrue(plan.meeting.old_business)
        self.assertEqual(plan.meeting.notes, "Hand edit")
        self.assertIn("Motion by Herm Walsh", plan.to_dict()["markdown"])


class PriorHttpTests(unittest.TestCase):
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

    def test_upload_returns_suggestions_without_saving_style(self):
        self._json(
            "POST",
            "/api/settings",
            {"setup_complete": True, "organization": "Harbor Light Squadron 3", "roster": ["Member A"]},
        )
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=prior_minutes&filename=prior.txt",
            raw=MOTION_BY.encode("utf-8"),
        )
        self.assertEqual(uploaded["document"]["label"], "prior_minutes")
        dest = Path(os.environ["QUORUM_VAULT"]) / "meetings" / mid / "docs" / "prior.txt"
        self.assertTrue(dest.is_file())
        scan = uploaded["prior_minutes_scan"]
        self.assertTrue(scan["found"])
        self.assertTrue(scan["style"])
        self.assertTrue(scan["preview"]["before"])
        self.assertTrue(scan["preview"]["after"])
        prefs = self._json("GET", "/api/settings")["settings"]
        self.assertNotIn("minutes_motion_phrasing", prefs)
        self.assertEqual(uploaded["meeting"]["old_business"], [])

    def test_confirm_fills_settings_and_old_business(self):
        self._json("POST", "/api/settings", {"setup_complete": True, "organization": "Harbor Light Squadron 3"})
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        scanned = self._json("POST", "/api/prior-minutes/scan", {"text": MOTION_BY, "filename": "prior.txt", "meeting_id": mid})
        scan = scanned["prior_minutes_scan"]
        confirmed = self._json(
            "POST",
            "/api/prior-minutes/confirm",
            {
                "meeting_id": mid,
                "style": [
                    {"confirm": True, "field": row["field"], "value": row["value"], "overwrite": True}
                    for row in scan["style"]
                ],
                "old_business": [{"confirm": True, "text": row["text"]} for row in scan["old_business"]],
            },
        )
        self.assertEqual(confirmed["settings"]["minutes_motion_phrasing"], "motion_by")
        self.assertEqual(confirmed["settings"]["minutes_name_style"], "full")
        self.assertTrue(confirmed["old_business"])
        self.assertTrue(confirmed["meeting"]["old_business"])
        self.assertIn("Motion by", confirmed["markdown"])

    def test_confirm_refuses_overwrite_without_flag(self):
        self._json("POST", "/api/settings", {"minutes_closing": "Leave this."})
        blocked = self._json(
            "POST",
            "/api/prior-minutes/confirm",
            {"style": [{"confirm": True, "overwrite": False, "field": "minutes_closing", "value": "For God and Country"}]},
        )
        self.assertEqual(blocked["settings"]["minutes_closing"], "Leave this.")
        self.assertEqual(blocked["applied"], [])

    def test_bad_scan_upload_keeps_file(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=prior_minutes&filename=bad_scan.jpg",
            raw=BAD_SCAN,
        )
        self.assertEqual(uploaded["document"]["label"], "prior_minutes")
        self.assertFalse(uploaded["prior_minutes_scan"]["found"])
        self.assertTrue(
            (Path(os.environ["QUORUM_VAULT"]) / "meetings" / mid / "docs" / "bad_scan.jpg").is_file()
        )
        prefs = self._json("GET", "/api/settings")["settings"]
        self.assertNotIn("minutes_motion_phrasing", prefs)

    def test_finance_upload_has_no_prior_scan(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        uploaded = self._json(
            "POST",
            f"/api/meetings/{mid}/documents?label=finance&filename=sheet.jpg",
            raw=b"sheet-bytes",
        )
        self.assertNotIn("prior_minutes_scan", uploaded)
        self.assertNotIn("bylaws_scan", uploaded)

    def test_preview_endpoint(self):
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        mid = created["meeting"]["id"]
        preview = self._json(
            "POST",
            "/api/prior-minutes/preview",
            {
                "meeting_id": mid,
                "style": [
                    {"confirm": True, "field": "minutes_motion_phrasing", "value": "motion_by"},
                    {"confirm": True, "field": "minutes_name_style", "value": "full"},
                ],
            },
        )
        self.assertIn("before", preview["preview"])
        self.assertIn("after", preview["preview"])


class PriorUiContractTests(unittest.TestCase):
    def test_labels_and_review_list(self):
        for needle in (
            'value="prior_minutes"',
            "Last accepted minutes",
            'id="prior-review"',
            'id="prior-suggestions"',
            'id="prior-preview"',
            'id="prior-preview-before"',
            'id="prior-preview-after"',
            'id="btn-prior-confirm"',
            'id="doc-photo-prior"',
            'id="doc-file-prior"',
            "Confirm selected",
            "Open minutes style",
        ):
            self.assertIn(needle, INDEX)
        self.assertLess(INDEX.index('id="btn-rec"'), INDEX.index('id="prior-review"'))
        self.assertLess(INDEX.index('id="bylaws-review"'), INDEX.index('id="prior-review"'))

    def test_record_still_available(self):
        self.assertIn('id="btn-rec"', INDEX)
        self.assertIn("Record", INDEX)
        start = APP_JS[APP_JS.index("async function startRec") : APP_JS.index("async function startRec") + 500]
        self.assertIn("hasOpenMeeting()", start)
        self.assertNotIn("prior", start)
        self.assertNotIn("bylaws", start)

    def test_suggestions_not_auto_applied_in_js(self):
        add = _fn(APP_JS, "addDocuments")
        self.assertIn("prior_minutes_scan", add)
        self.assertNotIn("/api/prior-minutes/confirm", add)
        self.assertNotIn("/api/settings", add)
        self.assertIn("showPriorScan", add)
        confirm = _fn(APP_JS, "confirmPriorSelected")
        self.assertIn("/api/prior-minutes/confirm", confirm)
        self.assertIn("fillWizardMinutesStyle", confirm)

    def test_doc_label_normalizes_prior_minutes(self):
        self.assertEqual(normalize_doc_label("prior_minutes"), "prior_minutes")
        self.assertEqual(normalize_doc_label("Last accepted minutes"), "prior_minutes")
        self.assertEqual(normalize_doc_label("minutes"), "prior_minutes")
        self.assertEqual(normalize_doc_label("mystery"), "other")

    def test_wizard_style_fields(self):
        for needle in (
            'id="wiz-minutes-name-style"',
            'id="wiz-minutes-motion"',
            'id="wiz-minutes-signature"',
            "Minutes closing line",
        ):
            self.assertIn(needle, INDEX)
        self.assertIn("readWizardMinutesStyle", APP_JS)
        show = APP_JS[APP_JS.index("function showWizard") : APP_JS.index("function showWizard") + 1100]
        self.assertIn("settings.minutes_closing", show)
        start = APP_JS[APP_JS.index("async function startRec") : APP_JS.index("async function startRec") + 500]
        self.assertNotIn("minutes_closing", start)


if __name__ == "__main__":
    unittest.main()
