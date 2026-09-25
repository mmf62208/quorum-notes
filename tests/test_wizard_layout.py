"""Static self-check: setup wizard stays reachable on a short hall laptop."""

from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "quorum" / "web"


class WizardLayoutTests(unittest.TestCase):
    def test_wizard_ids_and_short_viewport_scroll_css(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "styles.css").read_text(encoding="utf-8")
        for needle in ('id="wizard"', 'id="wiz-roster"', 'id="wiz-roster-confirm"', 'id="btn-wiz-save"', 'class="sheet"'):
            self.assertIn(needle, html)
        self.assertIn("wiz-body", html)
        self.assertIn("wiz-footer", html)
        self.assertIn("#wizard.sheet:not([hidden])", css)
        self.assertIn("flex-direction: column", css)
        self.assertIn("#wizard .wiz-body", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn("#wizard .wiz-footer", css)
        self.assertIn("position: sticky", css)
        self.assertIn("#wizard #wiz-roster", css)
        self.assertIn("max-height: min(16rem, 40vh)", css)
        self.assertLess(
            html.index('id="wiz-roster"'),
            html.index('id="btn-wiz-save"'),
            "Save must stay after the roster so Tab order is unchanged",
        )
        self.assertLess(html.index('id="wiz-roster-confirm"'), html.index('id="wiz-quorum"'))
        self.assertLess(html.index('id="wiz-quorum"'), html.index('id="btn-wiz-save"'))
        self.assertIn("Any special quorum rule?", html)
