import unittest

from quorum.minutes import (
    Meeting,
    Motion,
    Report,
    apply_motion_result,
    enforce_motion_rules,
    render_minutes,
)


class MinutesTests(unittest.TestCase):
    def test_majority_quorum(self):
        meeting = Meeting(
            id="t1",
            roster=["A", "B", "C", "D", "E"],
            present=["A", "B", "C"],
        )
        self.assertEqual(meeting.quorum_required(), 3)
        self.assertTrue(meeting.quorum_present())
        meeting.present = ["A", "B"]
        self.assertFalse(meeting.quorum_present())

    def test_fixed_quorum(self):
        meeting = Meeting(id="t2", roster=["A"], present=["A"], quorum_rule="fixed", quorum_fixed=7)
        self.assertEqual(meeting.quorum_required(), 7)
        self.assertFalse(meeting.quorum_present())

    def test_motion_needs_second_and_yeas(self):
        m = Motion(text="buy lumber", mover="Herm", yeas=6, nays=1)
        self.assertEqual(m.decide(), "failed")
        m.seconder = "Mike"
        self.assertEqual(m.decide(), "carried")

    def test_rr_cannot_carry_without_second(self):
        m = Motion(text="buy lumber", mover="Herm")
        with self.assertRaises(ValueError) as ctx:
            apply_motion_result(m, "carried", roberts=True)
        self.assertIn("second", str(ctx.exception).lower())
        self.assertEqual(m.result, "pending")
        apply_motion_result(m, "carried", roberts=False)
        self.assertEqual(m.result, "carried")
        m2 = Motion(text="buy lumber", mover="Herm", seconder="Mike")
        apply_motion_result(m2, "carried", roberts=True)
        self.assertEqual(m2.result, "carried")

    def test_enforce_motion_rules_blocks_carried_without_second(self):
        meeting = Meeting(
            id="rr1",
            roberts=True,
            new_business=[Motion(text="buy lumber", mover="Herm", result="carried")],
        )
        with self.assertRaises(ValueError):
            enforce_motion_rules(meeting)
        meeting.new_business[0].seconder = "Mike"
        self.assertIs(enforce_motion_rules(meeting), meeting)

    def test_render_includes_quorum_and_motion(self):
        meeting = Meeting(
            id="t3",
            organization="SAL Post 484 Squadron",
            date="2026-06-16",
            title="Regular Meeting",
            called_to_order_by="Commander Jeff Shumaker",
            location="Post home",
            roster=["Jeff Shumaker", "Mike Featherstone", "Herm Clear"],
            present=["Jeff Shumaker", "Mike Featherstone", "Herm Clear"],
            opening=["Chaplain offered the opening prayer."],
            previous_minutes="approved",
            reports=[Report(title="Finance", presenter="Ted Ruser", body="Checking $6,171.18")],
            new_business=[
                Motion(
                    text="SAL cover VA veterans’ meals",
                    mover="William Wood",
                    seconder="Herm Clear",
                    yeas=10,
                    nays=0,
                    result="carried",
                )
            ],
            submitted_by="Mike Featherstone",
            submitted_office="Adjutant, SAL Post 484",
        )
        text = render_minutes(meeting)
        self.assertIn("A quorum was present", text)
        self.assertIn("William Wood moved", text)
        self.assertIn("Respectfully submitted", text)
        self.assertIn("SAL Post 484", text)


if __name__ == "__main__":
    unittest.main()
