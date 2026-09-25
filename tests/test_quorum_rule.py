"""Org quorum rule: storage, evaluate, minutes line, and UI contract."""

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

from quorum import config, settings as app_settings, vault
from quorum.minutes import Meeting, render_minutes
from quorum.quorum_rule import (
    SAL_POST_484_RULE,
    apply_result_to_meeting,
    evaluate_quorum,
    normalize_quorum_rule,
    preview_rule,
    upsert_quorum_minutes_line,
)
from quorum.roster import normalize_title, titles_match
from quorum.server import Handler
from quorum.settings import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "quorum" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "styles.css").read_text(encoding="utf-8")
OLD_SETTINGS = Path(__file__).resolve().parent / "fixtures" / "old_settings.json"


def people(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "title": title} for name, title in pairs]


class QuorumRuleStorageTests(unittest.TestCase):
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

    def test_defaults_have_no_quorum_rule_key(self):
        self.assertNotIn("quorum_rule", DEFAULTS)

    def test_save_and_load_structured_text_none(self):
        structured = app_settings.save_settings({"quorum_rule": SAL_POST_484_RULE.to_dict()})
        self.assertEqual(structured["quorum_rule"]["mode"], "structured")
        self.assertEqual(structured["quorum_rule"]["presiding_any_of"], list(SAL_POST_484_RULE.presiding_any_of))
        self.assertEqual(structured["quorum_rule"]["min_other_officers"], 3)
        loaded = app_settings.load_settings()
        self.assertEqual(loaded["quorum_rule"]["notes"], SAL_POST_484_RULE.notes)

        text = app_settings.save_settings({"quorum_rule": {"mode": "text", "notes": "Ask the commander."}})
        self.assertEqual(text["quorum_rule"]["mode"], "text")
        self.assertEqual(app_settings.load_settings()["quorum_rule"]["notes"], "Ask the commander.")

        none = app_settings.save_settings({"quorum_rule": {"mode": "none"}})
        self.assertEqual(none["quorum_rule"]["mode"], "none")
        self.assertEqual(normalize_quorum_rule(app_settings.load_settings().get("quorum_rule")).mode, "none")

    def test_missing_key_loads_as_none(self):
        loaded = app_settings.load_settings()
        self.assertNotIn("quorum_rule", loaded)
        self.assertEqual(normalize_quorum_rule(loaded.get("quorum_rule")).mode, "none")
        raw_path = app_settings.settings_path()
        self.assertFalse(raw_path.is_file())

    def test_empty_title_resave_keeps_existing_titles(self):
        app_settings.save_settings(
            {
                "roster": ["Jeff Shumaker", "Herm Clear"],
                "roster_titles": {"Jeff Shumaker": "Commander", "Herm Clear": "Chaplain"},
            }
        )
        again = app_settings.save_settings(
            {"roster": ["Jeff Shumaker", "Herm Clear"], "roster_titles": {}}
        )
        self.assertEqual(again["roster_titles"]["Jeff Shumaker"], "Commander")
        self.assertEqual(again["roster_titles"]["Herm Clear"], "Chaplain")

    def test_old_vault_fixture_loads_unchanged(self):
        dest = app_settings.settings_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = OLD_SETTINGS.read_text(encoding="utf-8")
        dest.write_text(original, encoding="utf-8")
        loaded = app_settings.load_settings()
        self.assertNotIn("quorum_rule", json.loads(dest.read_text(encoding="utf-8")))
        self.assertEqual(normalize_quorum_rule(loaded.get("quorum_rule")).mode, "none")
        self.assertEqual(loaded["organization"], "SAL Post 484 Squadron")
        self.assertEqual(loaded["roster"], ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"])
        self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), json.loads(original))


class QuorumEvaluateTests(unittest.TestCase):
    def test_sal_commander_plus_three_officers_met(self):
        result = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jeff Shumaker", "Commander"),
                ("Herm Clear", "Chaplain"),
                ("Mike Featherstone", "Adjutant"),
                ("Ted Ruser", "Finance Officer"),
            ),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "met")
        self.assertEqual(result.other_officers, 3)
        self.assertIn("Quorum met", result.banner_title)
        self.assertIn("Commander presiding", result.minutes_line)

    def test_sal_commander_plus_two_officers_needs_one(self):
        result = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jeff Shumaker", "Commander"),
                ("Herm Clear", "Chaplain"),
                ("Mike Featherstone", "Adjutant"),
            ),
        )
        self.assertEqual(result.status, "not_met")
        self.assertEqual(result.need, "1 more officer")
        self.assertEqual(result.banner_title, "Not met: need 1 more officer")
        self.assertEqual(result.minutes_line, "Quorum: Not met (need 1 more officer).")

    def test_sal_first_vice_plus_three_officers_met(self):
        result = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jane Doe", "1st Vice Commander"),
                ("Herm Clear", "Chaplain"),
                ("Mike Featherstone", "Adjutant"),
                ("Ted Ruser", "Finance Officer"),
            ),
        )
        self.assertEqual(result.status, "met")
        self.assertEqual(result.presiding_title, "1st Vice Commander")

    def test_sal_commander_and_first_vice_plus_two_others_met(self):
        result = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jeff Shumaker", "Commander"),
                ("Jane Doe", "1st Vice Commander"),
                ("Herm Clear", "Chaplain"),
                ("Mike Featherstone", "Adjutant"),
            ),
        )
        self.assertEqual(result.status, "met")
        self.assertEqual(result.presiding_title, "Commander")
        self.assertEqual(result.other_officers, 3)

    def test_sal_five_officers_no_presiding_not_met(self):
        result = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Herm Clear", "Chaplain"),
                ("Mike Featherstone", "Adjutant"),
                ("Ted Ruser", "Finance Officer"),
                ("William Wood", "Sergeant-at-Arms"),
                ("Pat Lee", "Historian"),
            ),
        )
        self.assertEqual(result.status, "not_met")
        self.assertEqual(result.need, "Commander or 1st/2nd Vice")
        self.assertEqual(result.banner_title, "Not met: need Commander or 1st/2nd Vice")

    def test_sal_zero_present_lists_both_needs(self):
        result = evaluate_quorum(SAL_POST_484_RULE, [])
        self.assertEqual(result.status, "not_met")
        self.assertIn("Commander or 1st/2nd Vice", result.need)
        self.assertIn("3 more officers", result.need)
        self.assertEqual(result.need, "Commander or 1st/2nd Vice and 3 more officers")

    def test_title_normalization_and_non_officers(self):
        self.assertTrue(titles_match("commander", "Commander"))
        self.assertTrue(titles_match("1st Vice", "1st Vice Commander"))
        self.assertTrue(titles_match("First Vice Commander", "1st Vice Commander"))
        self.assertEqual(normalize_title("vice"), normalize_title("Vice Commander"))
        commander = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jeff", "commander"),
                ("A", "Chaplain"),
                ("B", "Adjutant"),
                ("C", "Historian"),
            ),
        )
        self.assertEqual(commander.status, "met")
        first_vice = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jane", "1st Vice"),
                ("A", "Chaplain"),
                ("B", "Adjutant"),
                ("C", "Historian"),
            ),
        )
        self.assertEqual(first_vice.status, "met")
        spelled = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jane", "First Vice Commander"),
                ("A", "Chaplain"),
                ("B", "Adjutant"),
                ("C", "Historian"),
            ),
        )
        self.assertEqual(spelled.status, "met")
        members = evaluate_quorum(
            SAL_POST_484_RULE,
            people(
                ("Jeff", "Commander"),
                ("A", "Member"),
                ("B", ""),
                ("C", "Chaplain"),
            ),
        )
        self.assertEqual(members.status, "not_met")
        self.assertEqual(members.need, "2 more officers")

    def test_headcount_only(self):
        rule = normalize_quorum_rule(
            {"mode": "structured", "presiding_any_of": [], "min_other_officers": 0, "min_members_total": 4}
        )
        short = evaluate_quorum(rule, people(("A", ""), ("B", "Member"), ("C", "Chaplain")))
        self.assertEqual(short.status, "not_met")
        self.assertEqual(short.need, "1 more member")
        ok = evaluate_quorum(rule, people(("A", ""), ("B", ""), ("C", ""), ("D", "")))
        self.assertEqual(ok.status, "met")
        self.assertIn("4 members present", ok.minutes_line)

    def test_text_and_none_modes(self):
        text = evaluate_quorum({"mode": "text", "notes": "Ask the commander."}, people(("Jeff", "Commander")))
        self.assertEqual(text.status, "manual")
        self.assertEqual(text.notes, "Ask the commander.")
        self.assertIn("Check quorum manually", text.banner_title)
        self.assertEqual(text.minutes_line, "Quorum rule: Ask the commander. (Checked manually.)")
        self.assertIsNone(evaluate_quorum({"mode": "none"}, people(("Jeff", "Commander"))))
        self.assertIsNone(evaluate_quorum(None, people(("Jeff", "Commander"))))

    def test_sal_preview_copy(self):
        self.assertEqual(
            preview_rule(SAL_POST_484_RULE),
            "Quorum = Commander or 1st/2nd Vice presiding, plus at least 3 other officers.",
        )


class QuorumMinutesLineTests(unittest.TestCase):
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

    def _meeting(self, **fields) -> Meeting:
        base = dict(
            id="q1",
            organization="SAL Post 484 Squadron",
            roster=["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"],
            present=["Jeff Shumaker", "Herm Clear", "Mike Featherstone"],
            roster_titles={
                "Jeff Shumaker": "Commander",
                "Herm Clear": "Chaplain",
                "Mike Featherstone": "Adjutant",
                "Ted Ruser": "Finance Officer",
            },
        )
        base.update(fields)
        return Meeting(**base)

    def test_rule_set_gives_only_b2_line(self):
        meeting = self._meeting(org_quorum_line="Quorum: Not met (need 1 more officer).")
        text = render_minutes(meeting)
        self.assertEqual(text.count("Quorum: Not met (need 1 more officer)."), 1)
        self.assertNotIn("A quorum was present", text)
        self.assertNotIn("A quorum was **not** present", text)
        self.assertLess(text.index("Members present"), text.index("Quorum: Not met"))
        self.assertLess(text.index("Quorum: Not met"), text.index("**Approval of Previous Minutes:**"))

    def test_no_rule_gives_only_old_line(self):
        text = render_minutes(self._meeting())
        self.assertIn("A quorum was present", text)
        self.assertEqual(text.count("A quorum was present"), 1)
        self.assertNotIn("Quorum: Met", text)
        self.assertNotIn("Quorum: Not met", text)
        self.assertNotIn("Checked manually", text)

    def test_text_rule_gives_only_manual_line(self):
        meeting = self._meeting(org_quorum_line="Quorum rule: Ask the commander. (Checked manually.)")
        text = render_minutes(meeting)
        self.assertIn("Quorum rule: Ask the commander. (Checked manually.)", text)
        self.assertEqual(text.count("Quorum rule: Ask the commander. (Checked manually.)"), 1)
        self.assertNotIn("A quorum was present", text)
        self.assertNotIn("A quorum was **not** present", text)

    def test_upsert_regenerates_and_does_not_duplicate(self):
        meeting = self._meeting(org_quorum_line="Quorum: Not met (need 1 more officer).")
        first = render_minutes(meeting)
        second = upsert_quorum_minutes_line(first, "Quorum: Met (Commander presiding; 3 other officers present).")
        third = upsert_quorum_minutes_line(second, "Quorum: Met (Commander presiding; 3 other officers present).")
        self.assertEqual(third.count("Quorum: Met (Commander presiding; 3 other officers present)."), 1)
        self.assertNotIn("Quorum: Not met", third)
        self.assertNotIn("A quorum was present", third)
        self.assertLess(third.index("Members present"), third.index("Quorum: Met"))

    def test_hand_edit_is_not_clobbered(self):
        meeting = self._meeting(
            org_quorum_line="Quorum: Met (hand-edited by the adjutant).",
            org_quorum_line_edited=True,
        )
        result = evaluate_quorum(SAL_POST_484_RULE, people(("Jeff Shumaker", "Commander")))
        apply_result_to_meeting(meeting, result)
        self.assertEqual(meeting.org_quorum_line, "Quorum: Met (hand-edited by the adjutant).")

    def test_save_regenerates_on_attendance_change(self):
        app_settings.save_settings(
            {
                "setup_complete": True,
                "organization": "SAL Post 484 Squadron",
                "quorum_rule": SAL_POST_484_RULE.to_dict(),
                "roster": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"],
                "roster_titles": {
                    "Jeff Shumaker": "Commander",
                    "Herm Clear": "Chaplain",
                    "Mike Featherstone": "Adjutant",
                    "Ted Ruser": "Finance Officer",
                },
            }
        )
        meeting = vault.create_meeting(
            {
                "title": "Regular Meeting",
                "present": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"],
                "roster": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"],
                "roster_titles": {
                    "Jeff Shumaker": "Commander",
                    "Herm Clear": "Chaplain",
                    "Mike Featherstone": "Adjutant",
                    "Ted Ruser": "Finance Officer",
                },
            }
        )
        first = render_minutes(meeting)
        self.assertIn("Quorum: Not met (need 1 more officer).", first)
        self.assertEqual(first.count("Quorum: Not met (need 1 more officer)."), 1)
        self.assertNotIn("A quorum was present", first)
        self.assertNotIn("A quorum was **not** present", first)
        meeting.present = ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"]
        vault.save_meeting(meeting)
        again = render_minutes(vault.load_meeting(meeting.id))
        self.assertIn("Quorum: Met (Commander presiding; 3 other officers present).", again)
        self.assertEqual(again.count("Quorum: Met (Commander presiding; 3 other officers present)."), 1)
        self.assertNotIn("Quorum: Not met", again)
        self.assertNotIn("A quorum was present", again)
        self.assertNotIn("A quorum was **not** present", again)


class QuorumUiContractTests(unittest.TestCase):
    def test_wizard_section_after_roster_before_save(self):
        for needle in (
            'id="wiz-quorum"',
            "Any special quorum rule?",
            "No special rule",
            "Pick officers + count",
            "Describe it in words",
            "Use example: SAL Post 484",
            'id="wiz-quorum-preview"',
            "Quorum rule",
            'id="org-quorum-banner"',
            'id="btn-org-quorum-edit"',
            'id="btn-org-quorum-dismiss"',
        ):
            self.assertIn(needle, INDEX)
        self.assertLess(INDEX.index('id="wiz-roster-confirm"'), INDEX.index('id="wiz-quorum"'))
        self.assertLess(INDEX.index('id="wiz-quorum"'), INDEX.index('id="btn-wiz-save"'))
        self.assertIn("overflow-y: auto", CSS)
        self.assertIn("position: sticky", CSS)

    def test_save_writes_rule_not_present(self):
        save_at = APP_JS.index("btn-wiz-save")
        chunk = APP_JS[save_at : save_at + 1100]
        self.assertIn("confirmedRosterNames", chunk)
        self.assertIn("quorum_rule", chunk)
        self.assertIn("applySal484Example", APP_JS)
        self.assertIn("evaluate_quorum", Path(ROOT / "quorum" / "quorum_rule.py").read_text(encoding="utf-8"))
        self.assertNotIn("present:", chunk)

    def test_record_not_gated_on_org_quorum(self):
        start = APP_JS[APP_JS.index("async function startRec") : APP_JS.index("async function startRec") + 500]
        self.assertIn("hasOpenMeeting()", start)
        self.assertNotIn("org_quorum", start)
        self.assertNotIn("evaluate_quorum", start)


class QuorumHttpTests(unittest.TestCase):
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

    def test_evaluate_endpoint_and_meeting_payload(self):
        self._json(
            "POST",
            "/api/settings",
            {
                "setup_complete": True,
                "quorum_rule": SAL_POST_484_RULE.to_dict(),
                "roster_titles": {"Jeff Shumaker": "Commander", "Herm Clear": "Chaplain", "Mike Featherstone": "Adjutant"},
            },
        )
        evaluated = self._json(
            "POST",
            "/api/quorum/evaluate",
            {"present": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"]},
        )
        self.assertEqual(evaluated["result"]["banner_title"], "Not met: need 1 more officer")
        created = self._json(
            "POST",
            "/api/meetings",
            {
                "title": "Regular Meeting",
                "present": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"],
                "roster_titles": {
                    "Jeff Shumaker": "Commander",
                    "Herm Clear": "Chaplain",
                    "Mike Featherstone": "Adjutant",
                },
            },
            code=201,
        )
        self.assertEqual(created["org_quorum"]["status"], "not_met")
        self.assertIn("Quorum: Not met (need 1 more officer).", created["markdown"])
        self.assertNotIn("A quorum was present", created["markdown"])
        self.assertNotIn("A quorum was **not** present", created["markdown"])


if __name__ == "__main__":
    unittest.main()
