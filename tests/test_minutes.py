import unittest

from quorum.minutes import Meeting, Motion, Report, render_minutes


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
