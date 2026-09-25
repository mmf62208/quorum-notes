"""Officer memory: persist, seed, carry-forward, roll call, quorum titles."""

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
from quorum.officers import (
    add_officer_role,
    apply_officer_titles,
    merge_officer_names,
    normalize_officers,
    officers_from_roster_titles,
    resolve_officers,
    swap_officer_name,
    titles_from_officers,
    vacate_officer,
)
from quorum.quorum_rule import SAL_POST_484_RULE, evaluate_quorum, present_people_from
from quorum.server import Handler
from quorum.settings import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "quorum" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "styles.css").read_text(encoding="utf-8")
OLD_SETTINGS = Path(__file__).resolve().parent / "fixtures" / "old_settings.json"
TITLES_NO_OFFICERS = Path(__file__).resolve().parent / "fixtures" / "roster_titles_no_officers.json"

SAL_OFFICERS = [
    {"role": "Commander", "name": "Jeff Shumaker"},
    {"role": "Chaplain", "name": "Herm Clear"},
    {"role": "Adjutant", "name": "Mike Featherstone"},
    {"role": "Finance Officer", "name": "Ted Ruser"},
]


def _people_from_officers(rows):
    return [{"name": row["name"], "title": row["role"]} for row in rows if row.get("name")]


class OfficerNormalizeTests(unittest.TestCase):
    def test_persist_shape_and_title_alias(self):
        loaded = normalize_officers(
            [
                {"role": "commander", "name": "  Jeff Shumaker "},
                {"title": "Chaplain", "name": "Herm Clear"},
                {"office": "Adjutant", "name": "Mike Featherstone"},
                {"role": "", "name": "Nobody"},
                "skip me",
            ]
        )
        self.assertEqual(
            [row.to_dict() for row in loaded],
            [
                {"role": "Commander", "name": "Jeff Shumaker"},
                {"role": "Chaplain", "name": "Herm Clear"},
                {"role": "Adjutant", "name": "Mike Featherstone"},
            ],
        )
        self.assertEqual(normalize_officers(None), [])
        self.assertEqual(normalize_officers({}), [])

    def test_swap_vacate_add(self):
        start = normalize_officers(SAL_OFFICERS)
        swapped = swap_officer_name(start, "Commander", "Jane Doe")
        self.assertEqual(titles_from_officers(swapped)["Jane Doe"], "Commander")
        self.assertNotIn("Jeff Shumaker", titles_from_officers(swapped))
        vacated = vacate_officer(swapped, "Chaplain")
        chaplain = next(row for row in vacated if row.role == "Chaplain")
        self.assertEqual(chaplain.name, "")
        self.assertIn("Chaplain", [row.role for row in vacated])
        added = add_officer_role(vacated, "Historian", "Pat Lee")
        self.assertEqual(titles_from_officers(added)["Pat Lee"], "Historian")

    def test_seed_from_roster_titles_skips_member(self):
        seeded = officers_from_roster_titles(
            {
                "Jeff Shumaker": "Commander",
                "Herm Clear": "Chaplain",
                "Guest": "Member",
                "Blank": "",
            }
        )
        self.assertEqual(
            [row.to_dict() for row in seeded],
            [
                {"role": "Commander", "name": "Jeff Shumaker"},
                {"role": "Chaplain", "name": "Herm Clear"},
            ],
        )
        self.assertEqual(resolve_officers({"roster_titles": {"Jeff Shumaker": "Commander"}}), seeded[:1])
        self.assertEqual(resolve_officers({"officers": [], "roster_titles": {"Jeff Shumaker": "Commander"}}), [])


class OfficerVaultTests(unittest.TestCase):
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

    def test_defaults_have_no_officers_key(self):
        self.assertNotIn("officers", DEFAULTS)
        loaded = app_settings.load_settings()
        self.assertNotIn("officers", loaded)

    def test_save_and_load_officers(self):
        saved = app_settings.save_settings({"officers": SAL_OFFICERS})
        self.assertEqual(saved["officers"][0], {"role": "Commander", "name": "Jeff Shumaker"})
        loaded = app_settings.load_settings()
        self.assertEqual(loaded["officers"], saved["officers"])
        again = app_settings.save_settings({"organization": "SAL Post 484 Squadron"})
        self.assertEqual(again["officers"][0]["name"], "Jeff Shumaker")

    def test_old_vault_fixture_loads_unchanged(self):
        dest = app_settings.settings_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = OLD_SETTINGS.read_text(encoding="utf-8")
        dest.write_text(original, encoding="utf-8")
        loaded = app_settings.load_settings()
        self.assertNotIn("officers", json.loads(dest.read_text(encoding="utf-8")))
        self.assertEqual(resolve_officers(loaded), [])
        self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), json.loads(original))

    def test_seed_from_setup_roster_titles_without_writing(self):
        dest = app_settings.settings_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = TITLES_NO_OFFICERS.read_text(encoding="utf-8")
        dest.write_text(original, encoding="utf-8")
        loaded = app_settings.load_settings()
        self.assertNotIn("officers", json.loads(dest.read_text(encoding="utf-8")))
        seeded = resolve_officers(loaded)
        self.assertEqual(seeded[0].role, "Commander")
        self.assertEqual(seeded[0].name, "Jeff Shumaker")
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        self.assertIn("Jeff Shumaker", meeting.roster)
        self.assertEqual(meeting.roster_titles["Jeff Shumaker"], "Commander")
        self.assertEqual(meeting.present, [])
        self.assertNotIn("officers", json.loads(dest.read_text(encoding="utf-8")))

    def test_create_meeting_without_memory_matches_today(self):
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        self.assertEqual(meeting.roster, DEFAULTS["roster"])
        self.assertEqual(meeting.present, [])
        self.assertEqual(meeting.roster_titles, {})

    def test_confirm_then_carry_forward(self):
        app_settings.save_settings(
            {
                "setup_complete": True,
                "roster": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"],
                "officers": SAL_OFFICERS,
            }
        )
        first = vault.create_meeting({"title": "June meeting"})
        self.assertEqual(first.present, [])
        for row in SAL_OFFICERS:
            self.assertIn(row["name"], first.roster)
            self.assertEqual(first.roster_titles[row["name"]], row["role"])
        second = vault.create_meeting({"title": "July meeting"})
        self.assertEqual(second.roster_titles["Jeff Shumaker"], "Commander")
        self.assertEqual(second.present, [])
        swapped = swap_officer_name(resolve_officers(app_settings.load_settings()), "Commander", "Jane Doe")
        app_settings.save_settings({"officers": [row.to_dict() for row in swapped]})
        third = vault.create_meeting({"title": "August meeting"})
        self.assertEqual(third.roster_titles["Jane Doe"], "Commander")
        self.assertNotIn("Jeff Shumaker", third.roster_titles)
        self.assertIn("Jeff Shumaker", third.roster)
        self.assertEqual(third.present, [])

    def test_vacate_and_add_persist(self):
        officers = normalize_officers(SAL_OFFICERS)
        officers = vacate_officer(officers, "Finance Officer")
        officers = add_officer_role(officers, "Historian", "Pat Lee")
        app_settings.save_settings({"officers": [row.to_dict() for row in officers]})
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        self.assertNotIn("Ted Ruser", meeting.roster_titles)
        self.assertEqual(meeting.roster_titles["Pat Lee"], "Historian")
        self.assertIn("Pat Lee", meeting.roster)
        self.assertEqual(meeting.present, [])
        loaded = resolve_officers(app_settings.load_settings())
        finance = next(row for row in loaded if row.role == "Finance Officer")
        self.assertEqual(finance.name, "")

    def test_roll_call_prelists_officers_not_present(self):
        app_settings.save_settings({"officers": SAL_OFFICERS})
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        self.assertEqual(meeting.present, [])
        self.assertTrue(all(meeting.roster_titles[name] for name in titles_from_officers(normalize_officers(SAL_OFFICERS))))
        people = present_people_from(meeting.present, meeting.roster_titles)
        self.assertEqual(people, [])

    def test_quorum_uses_remembered_titles_sal_484(self):
        app_settings.save_settings(
            {
                "quorum_rule": SAL_POST_484_RULE.to_dict(),
                "officers": SAL_OFFICERS,
            }
        )
        remembered = titles_from_officers(resolve_officers(app_settings.load_settings()))
        met = evaluate_quorum(SAL_POST_484_RULE, present_people_from(list(remembered), remembered))
        self.assertEqual(met.status, "met")
        self.assertEqual(met.presiding_title, "Commander")
        self.assertEqual(met.other_officers, 3)
        short = evaluate_quorum(
            SAL_POST_484_RULE,
            present_people_from(["Jeff Shumaker", "Herm Clear", "Mike Featherstone"], remembered),
        )
        self.assertEqual(short.status, "not_met")
        self.assertEqual(short.need, "1 more officer")
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        empty = vault.org_quorum_for(meeting)
        self.assertEqual(empty["status"], "not_met")
        meeting.present = ["Jeff Shumaker", "Herm Clear", "Mike Featherstone"]
        vault.save_meeting(meeting)
        not_met = vault.org_quorum_for(vault.load_meeting(meeting.id))
        self.assertEqual(not_met["banner_title"], "Not met: need 1 more officer")
        meeting.present = ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"]
        vault.save_meeting(meeting)
        ok = vault.org_quorum_for(vault.load_meeting(meeting.id))
        self.assertEqual(ok["status"], "met")
        self.assertIn("Commander presiding", ok["minutes_line"])

    def test_stale_setup_title_does_not_override_swap(self):
        titles = apply_officer_titles(
            {"Jeff Shumaker": "Commander", "Herm Clear": "Chaplain"},
            swap_officer_name(normalize_officers(SAL_OFFICERS[:2]), "Commander", "Jane Doe"),
        )
        self.assertEqual(titles["Jane Doe"], "Commander")
        self.assertNotIn("Jeff Shumaker", titles)
        self.assertEqual(titles["Herm Clear"], "Chaplain")

    def test_explicit_roster_is_unchanged(self):
        app_settings.save_settings({"officers": SAL_OFFICERS})
        meeting = vault.create_meeting({"title": "Regular Meeting", "roster": []})
        self.assertEqual(meeting.roster, [])
        self.assertEqual(meeting.present, [])


class OfficerUiContractTests(unittest.TestCase):
    def test_start_meeting_sheet_and_sticky_confirm(self):
        for needle in (
            'id="officer-sheet"',
            "Same officers as last time?",
            'id="btn-officer-confirm"',
            "Confirm",
            "vacate a role",
            "Add a role",
            'id="officer-list"',
        ):
            self.assertIn(needle, INDEX)
        self.assertIn("Vacate", APP_JS)
        self.assertIn("#officer-sheet.sheet:not([hidden])", CSS)
        self.assertIn("#officer-sheet .wiz-body", CSS)
        self.assertIn("overflow-y: auto", CSS)
        self.assertIn("#officer-sheet .wiz-footer", CSS)
        self.assertIn("position: sticky", CSS)
        self.assertLess(INDEX.index('id="officer-list"'), INDEX.index('id="btn-officer-confirm"'))

    def test_confirm_and_roll_call_do_not_mark_present(self):
        self.assertIn("shouldAskOfficers", APP_JS)
        self.assertIn("confirmOfficersAndStart", APP_JS)
        confirm_at = APP_JS.index("async function confirmOfficersAndStart")
        chunk = APP_JS[confirm_at : confirm_at + 700]
        self.assertIn("/api/meetings", chunk)
        self.assertNotIn("present:", chunk)
        self.assertIn("titleForName", APP_JS)
        self.assertIn("${title}: ${name}", APP_JS)
        self.assertIn("rememberedOfficersFromSettings().forEach((row) => add(row.role))", APP_JS)

    def test_record_not_gated_on_officers(self):
        start = APP_JS[APP_JS.index("async function startRec") : APP_JS.index("async function startRec") + 500]
        self.assertIn("hasOpenMeeting()", start)
        self.assertNotIn("officer", start)
        self.assertNotIn("shouldAskOfficers", start)


class OfficerHttpTests(unittest.TestCase):
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

    def test_settings_and_meeting_and_quorum_from_officers(self):
        saved = self._json(
            "POST",
            "/api/settings",
            {
                "setup_complete": True,
                "quorum_rule": SAL_POST_484_RULE.to_dict(),
                "officers": SAL_OFFICERS,
            },
        )
        self.assertEqual(saved["settings"]["officers"][0]["role"], "Commander")
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        meeting = created["meeting"]
        self.assertEqual(meeting["present"], [])
        self.assertEqual(meeting["roster_titles"]["Jeff Shumaker"], "Commander")
        self.assertEqual(created["org_quorum"]["status"], "not_met")
        evaluated = self._json(
            "POST",
            "/api/quorum/evaluate",
            {"present": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"]},
        )
        self.assertEqual(evaluated["result"]["status"], "met")
        self.assertIn("Commander presiding", evaluated["result"]["minutes_line"])
        updated = self._json(
            "PUT",
            f"/api/meetings/{meeting['id']}",
            {**meeting, "present": ["Jeff Shumaker", "Herm Clear", "Mike Featherstone", "Ted Ruser"]},
        )
        self.assertEqual(updated["org_quorum"]["status"], "met")
        swapped = list(SAL_OFFICERS)
        swapped[0] = {"role": "Commander", "name": "Jane Doe"}
        self._json("POST", "/api/settings", {"officers": swapped})
        next_meeting = self._json("POST", "/api/meetings", {"title": "Next meeting"}, code=201)
        self.assertEqual(next_meeting["meeting"]["roster_titles"]["Jane Doe"], "Commander")
        self.assertNotIn("Jeff Shumaker", next_meeting["meeting"]["roster_titles"])
        self.assertEqual(next_meeting["meeting"]["present"], [])


class OfficerMergeTests(unittest.TestCase):
    def test_merge_skips_vacated_and_duplicates(self):
        names = merge_officer_names(
            ["Jeff Shumaker"],
            normalize_officers(
                [
                    {"role": "Commander", "name": "Jeff Shumaker"},
                    {"role": "Chaplain", "name": ""},
                    {"role": "Adjutant", "name": "Mike Featherstone"},
                ]
            ),
        )
        self.assertEqual(names, ["Jeff Shumaker", "Mike Featherstone"])


if __name__ == "__main__":
    unittest.main()
