"""Round C1 minutes house style: headers, names, motions, quorum, signature."""

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
from quorum.minutes import (
    SAL_POST_484_CLOSING,
    Meeting,
    Motion,
    Report,
    SpeakerMark,
    Takeaway,
    render_minutes,
)
from quorum.name_style import names_from_meeting, style_for_names
from quorum.quorum_rule import SAL_POST_484_RULE, apply_result_to_meeting, evaluate_quorum
from quorum.server import Handler
from quorum.settings import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "quorum" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
OLD_SETTINGS = Path(__file__).resolve().parent / "fixtures" / "old_settings.json"

SYNTHETIC_TITLES = {
    "Pat Hale": "Commander",
    "Chris Lang": "1st Vice",
    "Sam Ortiz": "2nd Vice",
    "Ted Brooks": "Finance Officer",
    "Mike Foster": "Adjutant",
    "Randy Cole": "Sgt. at Arms",
    "Herm Walsh": "Chaplain",
    "Mike Grant": "Historian",
}

SYNTHETIC_ROSTER = list(SYNTHETIC_TITLES)


def sep22_shaped_meeting(**overrides) -> Meeting:
    """Synthetic Sep-22-shaped meeting. No real member names."""
    fields = dict(
        id="sep22-shaped",
        title="Regular Meeting",
        organization="Example Squadron 12",
        date="September 22, 2026",
        location="Post home",
        called_to_order_by="Commander Pat Hale",
        opening=[
            "Chaplain Herm Walsh offered the opening prayer.",
            "The Pledge of Allegiance was recited.",
            "A moment of silence was observed in honor of POW/MIA.",
        ],
        roster=list(SYNTHETIC_ROSTER),
        present=[
            "Pat Hale",
            "Sam Ortiz",
            "Ted Brooks",
            "Mike Foster",
            "Randy Cole",
            "Herm Walsh",
            "Mike Grant",
        ],
        guests=["Alex Reed"],
        roster_titles=dict(SYNTHETIC_TITLES),
        previous_minutes="approved",
        reports=[
            Report(
                title="Membership / Adjutant",
                presenter="Mike Foster",
                body="- About 230 current paid members.\n- Seven new members presented for acceptance.",
            ),
            Report(
                title="Finance Officer",
                presenter="Ted Brooks",
                body="Presented the printed financial report for June-August activity.",
            ),
        ],
        old_business=[
            "Kitchen utilities: no new motion.",
            "Standing rules: no motion.",
        ],
        new_business=[
            Motion(
                text="accept the financial report as presented",
                mover="Herm Walsh",
                seconder="Randy Cole",
                yeas=7,
                nays=0,
                result="carried",
            ),
            Motion(
                text="donate $200 to the quarter auction",
                mover="Herm Walsh",
                seconder="Randy Cole",
                yeas=7,
                nays=0,
                result="carried",
            ),
        ],
        announcements=["Next breakfast is Sunday, October 11, 2026, 8:00 a.m."],
        adjournment="With no further business, the meeting was adjourned.",
        submitted_by="Mike Foster",
        submitted_office="Adjutant",
        closing="For God and Country",
        org_quorum_line="Quorum: Met (Commander presiding; 6 other officers present).",
        takeaways=[Takeaway(text="Replenish the cash box before breakfast", owner="Ted Brooks")],
    )
    fields.update(overrides)
    return Meeting(**fields)


class HouseStyleHeaderTests(unittest.TestCase):
    def test_run_in_headers_vs_list_sections(self):
        text = render_minutes(sep22_shaped_meeting())
        self.assertIn(
            "**Meeting Called to Order:** The regular meeting of Example Squadron 12 was called to order by Commander Pat Hale at Post home.",
            text,
        )
        self.assertIn("**Approval of Previous Minutes:** The minutes of the previous meeting were approved as printed.", text)
        self.assertIn(
            "**Finance Officer (Ted):** Presented the printed financial report for June-August activity.",
            text,
        )
        self.assertIn("**Adjournment:** With no further business, the meeting was adjourned.", text)
        self.assertIn("**Roll Call / Quorum:** Commander Pat Hale conducted roll call.", text)
        self.assertRegex(text, r"\*\*Opening Ceremonies:\*\*\n\* Chaplain Herm Walsh")
        self.assertRegex(text, r"\*\*Officers:\*\*\n\* Commander Pat Hale")
        self.assertRegex(text, r"\*\*Membership / Adjutant \(Mike F\.\):\*\*\n\* About 230")
        self.assertRegex(text, r"\*\*Old Business:\*\*\n\* Kitchen utilities")
        self.assertRegex(text, r"\*\*New Business:\*\*\n1\. Herm moved")
        self.assertNotIn("**Opening Ceremonies:**\n\n", text)
        self.assertNotIn("**Officers:**\n\n", text)


class HouseStyleNameTests(unittest.TestCase):
    def test_unique_first_names_in_body_and_full_names_on_roll(self):
        text = render_minutes(sep22_shaped_meeting())
        self.assertIn("* Commander Pat Hale, present", text)
        self.assertIn("* Chaplain Herm Walsh, present", text)
        self.assertIn("* 1st Vice Commander Chris Lang, absent", text)
        self.assertIn("Herm moved to accept the financial report as presented; Randy seconded.", text)
        self.assertIn("**Finance Officer (Ted):**", text)
        self.assertNotIn("Herm Walsh moved", text)
        self.assertNotIn("Ted Brooks seconded", text)

    def test_mike_f_mike_g_disambiguation(self):
        text = render_minutes(sep22_shaped_meeting())
        self.assertIn("Mike Foster (Mike F.)", text)
        self.assertIn("Mike Grant (Mike G.)", text)
        self.assertIn("**Membership / Adjutant (Mike F.):**", text)
        style = style_for_names(names_from_meeting(sep22_shaped_meeting()))
        self.assertEqual(style.spoken("Mike Foster"), "Mike F.")
        self.assertEqual(style.spoken("Mike Grant"), "Mike G.")
        self.assertEqual(style.spoken("Ted Brooks"), "Ted")

    def test_colliding_initials_use_fuller_name(self):
        meeting = sep22_shaped_meeting(
            roster=["Mike Foster", "Mike Finch", "Ted Brooks"],
            present=["Mike Foster", "Mike Finch", "Ted Brooks"],
            roster_titles={
                "Mike Foster": "Adjutant",
                "Mike Finch": "Historian",
                "Ted Brooks": "Finance Officer",
            },
            guests=[],
            new_business=[
                Motion(
                    text="pay the bills as presented",
                    mover="Mike Foster",
                    seconder="Mike Finch",
                    result="carried",
                )
            ],
            reports=[],
            closing="",
            minutes_closing="",
        )
        text = render_minutes(meeting)
        self.assertIn("Mike Foster moved to pay the bills as presented; Mike Finch seconded.", text)
        self.assertNotIn("Mike F. moved", text)
        self.assertNotIn("Mike F.", text)
        self.assertIn("Adjutant Mike Foster", text)
        self.assertIn("Historian Mike Finch", text)

    def test_officer_memory_and_roster_are_the_name_source(self):
        meeting = Meeting(
            id="memory",
            roster=["Pat Hale", "Alex Reed"],
            present=["Pat Hale", "Alex Reed"],
            roster_titles={"Pat Hale": "Commander", "Mike Foster": "Adjutant", "Mike Grant": "Historian"},
            new_business=[
                Motion(text="approve the agenda", mover="Mike Foster", seconder="Pat Hale", result="carried")
            ],
        )
        style = style_for_names(names_from_meeting(meeting))
        self.assertEqual(style.spoken("Mike Foster"), "Mike F.")
        self.assertEqual(style.spoken("Mike Grant"), "Mike G.")
        self.assertEqual(style.spoken("Pat Hale"), "Pat")
        text = render_minutes(meeting)
        self.assertIn("Mike F. moved to approve the agenda; Pat seconded.", text)
        self.assertIn("Adjutant Mike Foster (Mike F.)", text)


class HouseStyleMotionTests(unittest.TestCase):
    def test_mover_second_result_phrasing(self):
        text = render_minutes(sep22_shaped_meeting())
        self.assertIn("Herm moved to accept the financial report as presented; Randy seconded. Motion carried.", text)
        self.assertIn("Herm moved to donate $200 to the quarter auction; Randy seconded. Motion carried.", text)
        self.assertNotIn("moved that", text)
        self.assertNotIn("The motion carried", text)


class HouseStyleQuorumTests(unittest.TestCase):
    def test_single_b2_quorum_line_preserved(self):
        meeting = sep22_shaped_meeting()
        text = render_minutes(meeting)
        line = "Quorum: Met (Commander presiding; 6 other officers present)."
        self.assertEqual(text.count(line), 1)
        self.assertNotIn("A quorum was present", text)
        self.assertNotIn("A quorum was **not** present", text)
        self.assertLess(text.index("**Officers:**"), text.index(line))
        self.assertLess(text.index(line), text.index("**Approval of Previous Minutes:**"))

    def test_hand_edited_quorum_line_is_not_clobbered(self):
        meeting = sep22_shaped_meeting(
            org_quorum_line="Quorum: Met (hand-edited by the adjutant).",
            org_quorum_line_edited=True,
        )
        result = evaluate_quorum(
            SAL_POST_484_RULE,
            [{"name": "Pat Hale", "title": "Commander"}],
        )
        apply_result_to_meeting(meeting, result)
        self.assertEqual(meeting.org_quorum_line, "Quorum: Met (hand-edited by the adjutant).")
        text = render_minutes(meeting)
        self.assertEqual(text.count("Quorum: Met (hand-edited by the adjutant)."), 1)
        self.assertNotIn("A quorum was present", text)


class HouseStyleSignatureTests(unittest.TestCase):
    def test_signature_with_closing_line(self):
        text = render_minutes(sep22_shaped_meeting())
        self.assertIn("**Respectfully submitted,**", text)
        self.assertIn("**Mike Foster**", text)
        self.assertIn("**Adjutant, Example Squadron 12**", text)
        self.assertIn(f"**{SAL_POST_484_CLOSING}**", text)
        submitted_at = text.index("**Respectfully submitted,**")
        self.assertLess(submitted_at, text.index("**Mike Foster**"))
        self.assertLess(text.index("**Mike Foster**"), text.index("**Adjutant, Example Squadron 12**"))
        self.assertLess(text.index("**Adjutant, Example Squadron 12**"), text.index(f"**{SAL_POST_484_CLOSING}**"))

    def test_signature_without_closing_line(self):
        text = render_minutes(sep22_shaped_meeting(closing="", minutes_closing=""))
        self.assertIn("**Respectfully submitted,**", text)
        self.assertIn("**Adjutant, Example Squadron 12**", text)
        self.assertNotIn(SAL_POST_484_CLOSING, text)
        self.assertNotIn("**For God and Country**", text)

    def test_no_em_dashes_in_generated_text(self):
        meeting = sep22_shaped_meeting(
            speaker_marks=[SpeakerMark(seconds=75, name="Ted Brooks")],
        )
        text = render_minutes(meeting)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("—", text)
        self.assertIn("* Replenish the cash box before breakfast (Ted Brooks)", text)
        self.assertIn("* 01:15 Ted Brooks", text)


class HouseStyleSettingsTests(unittest.TestCase):
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

    def test_defaults_have_no_minutes_closing_key(self):
        self.assertNotIn("minutes_closing", DEFAULTS)

    def test_save_and_load_closing_line(self):
        saved = app_settings.save_settings({"minutes_closing": f"  {SAL_POST_484_CLOSING}  "})
        self.assertEqual(saved["minutes_closing"], SAL_POST_484_CLOSING)
        self.assertEqual(app_settings.load_settings()["minutes_closing"], SAL_POST_484_CLOSING)
        blank = app_settings.save_settings({"minutes_closing": ""})
        self.assertEqual(blank["minutes_closing"], "")
        self.assertEqual(app_settings.load_settings()["minutes_closing"], "")

    def test_old_vault_has_no_closing_and_still_renders(self):
        dest = app_settings.settings_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = OLD_SETTINGS.read_text(encoding="utf-8")
        dest.write_text(original, encoding="utf-8")
        loaded = app_settings.load_settings()
        self.assertNotIn("minutes_closing", json.loads(dest.read_text(encoding="utf-8")))
        self.assertNotIn("minutes_closing", loaded)
        self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), json.loads(original))
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        text = render_minutes(meeting)
        self.assertIn("Respectfully submitted", text)
        self.assertNotIn(SAL_POST_484_CLOSING, text)
        self.assertEqual(meeting.minutes_closing, "")

    def test_create_meeting_uses_org_closing_and_blank_omits_line(self):
        app_settings.save_settings(
            {
                "setup_complete": True,
                "organization": "Example Squadron 12",
                "submitted_by": "Mike Foster",
                "submitted_office": "Adjutant",
                "minutes_closing": SAL_POST_484_CLOSING,
            }
        )
        meeting = vault.create_meeting({"title": "Regular Meeting"})
        self.assertEqual(meeting.minutes_closing, SAL_POST_484_CLOSING)
        text = render_minutes(meeting)
        self.assertIn(f"**{SAL_POST_484_CLOSING}**", text)
        app_settings.save_settings({"minutes_closing": ""})
        meeting.present = ["Mike Foster"]
        vault.save_meeting(meeting)
        again = render_minutes(vault.load_meeting(meeting.id))
        self.assertNotIn(SAL_POST_484_CLOSING, again)


class HouseStyleUiContractTests(unittest.TestCase):
    def test_setup_field_and_prefill_not_auto_applied(self):
        for needle in (
            'id="wiz-minutes-style"',
            'id="wiz-minutes-closing"',
            'id="btn-wiz-closing-sal"',
            "Use example: For God and Country",
            "Minutes closing line",
        ):
            self.assertIn(needle, INDEX)
        self.assertLess(INDEX.index('id="wiz-quorum"'), INDEX.index('id="wiz-minutes-closing"'))
        self.assertLess(INDEX.index('id="wiz-minutes-closing"'), INDEX.index('id="btn-wiz-save"'))
        self.assertIn("applySal484Closing", APP_JS)
        self.assertIn('SAL_484_CLOSING = "For God and Country"', APP_JS)
        save_at = APP_JS.index("btn-wiz-save")
        chunk = APP_JS[save_at : save_at + 1400]
        self.assertIn("minutes_closing", chunk)
        show = APP_JS[APP_JS.index("function showWizard") : APP_JS.index("function showWizard") + 900]
        self.assertIn("settings.minutes_closing", show)
        self.assertNotIn("applySal484Closing()", show)
        start = APP_JS[APP_JS.index("async function startRec") : APP_JS.index("async function startRec") + 500]
        self.assertNotIn("minutes_closing", start)
        self.assertNotIn("org_quorum", start)


class HouseStyleHttpTests(unittest.TestCase):
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

    def test_settings_closing_roundtrip_on_meeting(self):
        self._json(
            "POST",
            "/api/settings",
            {
                "setup_complete": True,
                "organization": "Example Squadron 12",
                "submitted_by": "Mike Foster",
                "submitted_office": "Adjutant",
                "minutes_closing": SAL_POST_484_CLOSING,
                "roster": ["Pat Hale", "Mike Foster", "Mike Grant"],
                "roster_titles": {
                    "Pat Hale": "Commander",
                    "Mike Foster": "Adjutant",
                    "Mike Grant": "Historian",
                },
            },
        )
        created = self._json("POST", "/api/meetings", {"title": "Regular Meeting"}, code=201)
        self.assertIn(SAL_POST_484_CLOSING, created["markdown"])
        self.assertEqual(created["meeting"]["minutes_closing"], SAL_POST_484_CLOSING)
        self._json("POST", "/api/settings", {"minutes_closing": ""})
        mid = created["meeting"]["id"]
        saved = self._json("PUT", f"/api/meetings/{mid}", created["meeting"])
        self.assertNotIn(SAL_POST_484_CLOSING, saved["markdown"])


if __name__ == "__main__":
    unittest.main()
