from django.test import TestCase

from apps.assessments.exams import profile_for
from apps.assessments.notes import blank_count, items_from_notes, render_notes_html


class ExamProfileTests(TestCase):
    def test_profiles_cover_center_languages(self):
        for code in ["en", "de", "fr", "es", "it", "zh", "ja", "ko", "ar", "tr", "ru"]:
            profile = profile_for(code)
            self.assertTrue(profile["exam"])
            self.assertEqual(len(profile["tfng"]), 3)

    def test_russian_labels(self):
        profile = profile_for("ru")
        self.assertEqual(profile["exam"], "ТРКИ")
        self.assertEqual(profile["tfng"][2][1], "В тексте не сказано")

    def test_notes_blanks(self):
        body = "Name: {1}\n## Cost\n* Total {2} including disk\n"
        self.assertEqual(blank_count(body), 2)
        items = items_from_notes(body, "frame, 195 / one nine five")
        self.assertEqual(items[0]["correct"], ["frame"])
        self.assertEqual(items[1]["correct"], ["195", "one nine five"])
        html = str(render_notes_html(body, "q_9", 1))
        self.assertIn("nb-num", html)
        self.assertIn('name="q_9_0"', html)
        self.assertIn("Cost", html)
