from django.test import TestCase

from apps.core.grading import grade_objective


class GradingTests(TestCase):
    def test_single_choice(self):
        ratio, auto = grade_objective({"kind": "single", "correct": "яблоко"}, "Яблоко")
        self.assertTrue(auto)
        self.assertEqual(ratio, 1)

    def test_multiple_choice(self):
        ratio, _ = grade_objective({"kind": "multiple", "correct": ["a", "c"]}, ["c", "a"])
        self.assertEqual(ratio, 1)

    def test_fill_blank(self):
        ratio, _ = grade_objective({"kind": "fill_blank", "correct": ["has", "Has"]}, " has ")
        self.assertEqual(ratio, 1)

    def test_match(self):
        ratio, _ = grade_objective({"kind": "match", "correct": {"cat": "кот"}}, {"cat": "кот"})
        self.assertEqual(ratio, 1)

    def test_tfng(self):
        ratio, auto = grade_objective({"kind": "tfng", "correct": "not_given"}, "Not_Given")
        self.assertTrue(auto)
        self.assertEqual(ratio, 1)

    def test_completion_items(self):
        payload = {
            "kind": "fill_blank",
            "items": [
                {"prompt": "every ____", "correct": ["Saturday"]},
                {"prompt": "more than ____", "correct": ["2000", "two thousand"]},
            ],
        }
        ratio, auto = grade_objective(payload, ["saturday", "two thousand"])
        self.assertTrue(auto)
        self.assertEqual(ratio, 1)

    def test_slash_alternatives(self):
        ratio, _ = grade_objective({"kind": "fill_blank", "correct": "colour/color"}, "Color")
        self.assertEqual(ratio, 1)
