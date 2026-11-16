from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.groups.models import Enrollment, Group, Language
from apps.homework.models import Assignment, Submission
from apps.notifications.models import TelegramHomeworkPick
from apps.notifications.telegram import finish_upload, prepare_update, save_homework_upload


class TelegramHomeworkTests(TestCase):
    def setUp(self):
        language = Language.objects.create(code="en", name="Английский")
        self.teacher = User.objects.create_user(
            login="t.bot",
            password="Teacher123!",
            role=User.Role.TEACHER,
            first_name="Анна",
            last_name="Тест",
        )
        self.student = User.objects.create_user(
            login="s.bot",
            password="Student123!",
            role=User.Role.STUDENT,
            first_name="Иван",
            last_name="Ученик",
            telegram_id=1001,
        )
        self.group = Group.objects.create(name="EN A1", language=language, teacher=self.teacher)
        Enrollment.objects.create(student=self.student, group=self.group)
        self.soon = Assignment.objects.create(
            title="Эссе",
            group=self.group,
            created_by=self.teacher,
            deadline=timezone.now() + timedelta(days=2),
            is_published=True,
        )
        self.later = Assignment.objects.create(
            title="Грамматика",
            group=self.group,
            created_by=self.teacher,
            deadline=timezone.now() + timedelta(days=9),
            is_published=True,
        )
        self.open_ended = Assignment.objects.create(
            title="Словарь",
            group=self.group,
            created_by=self.teacher,
            is_published=True,
        )

    def test_homework_button_lists_dates(self):
        action = prepare_update(
            {
                "callback_query": {
                    "id": "cb1",
                    "data": "hwmenu",
                    "from": {"id": 1001},
                    "message": {"chat": {"id": 1001}},
                }
            }
        )
        self.assertEqual(action.kind, "homework_dates")
        labels = [row[0]["text"] for row in action.markup["inline_keyboard"]]
        self.assertTrue(any(label.endswith("· 1") for label in labels))
        self.assertIn("Без срока · 1", labels)

    def test_date_then_file_lands_on_platform(self):
        day = timezone.localtime(self.soon.deadline).date().isoformat()
        listed = prepare_update(
            {
                "callback_query": {
                    "id": "cb2",
                    "data": f"hwd:{day}",
                    "from": {"id": 1001},
                    "message": {"chat": {"id": 1001}},
                }
            }
        )
        titles = [row[0]["text"] for row in listed.markup["inline_keyboard"]]
        self.assertIn("Эссе", titles)
        self.assertNotIn("Грамматика", titles)

        chosen = prepare_update(
            {
                "callback_query": {
                    "id": "cb3",
                    "data": f"hw:{self.soon.pk}",
                    "from": {"id": 1001},
                    "message": {"chat": {"id": 1001}},
                }
            }
        )
        self.assertEqual(chosen.kind, "await_file")
        self.assertTrue(TelegramHomeworkPick.objects.filter(user=self.student, assignment=self.soon).exists())

        incoming = prepare_update(
            {
                "message": {
                    "chat": {"id": 1001},
                    "from": {"id": 1001},
                    "photo": [{"file_id": "small"}, {"file_id": "big"}],
                    "caption": "Готово",
                }
            }
        )
        saved = finish_upload(incoming, "photo.jpg", b"image-bytes")
        self.assertEqual(saved.kind, "saved")
        submission = Submission.objects.get(assignment=self.soon, student=self.student)
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        self.assertEqual(submission.answer, "Готово")
        self.assertEqual(submission.files.count(), 1)
        self.assertEqual(submission.files.get().original_name, "photo.jpg")

    def test_file_without_choice_asks_to_open_homework(self):
        self.assertEqual(save_homework_upload(self.student, "a.txt", b"abc"), "no_pick")

    def test_student_menu_shows_deadlines_and_submissions(self):
        menu = prepare_update({"message": {"chat": {"id": 1001}, "from": {"id": 1001}, "text": "/menu"}})
        self.assertEqual(menu.kind, "menu")
        labels = [button["text"] for row in menu.markup["inline_keyboard"] for button in row]
        self.assertEqual(labels, ["Сдать домашку", "Мои работы", "Сроки"])

        deadlines = prepare_update({"message": {"chat": {"id": 1001}, "from": {"id": 1001}, "text": "Сроки"}})
        self.assertEqual(deadlines.kind, "deadlines")
        self.assertIn("Эссе", deadlines.text)
        self.assertIn("Словарь", deadlines.text)

        Submission.objects.create(
            assignment=self.soon,
            student=self.student,
            status=Submission.Status.GRADED,
            score=90,
        )
        status = prepare_update({"message": {"chat": {"id": 1001}, "from": {"id": 1001}, "text": "Мои работы"}})
        self.assertEqual(status.kind, "mystatus")
        self.assertIn("проверено", status.text)
        self.assertIn("90/100", status.text)

    def test_teacher_menu_lists_pending_and_groups(self):
        self.teacher.telegram_id = 2002
        self.teacher.save(update_fields=["telegram_id"])
        Submission.objects.create(
            assignment=self.soon,
            student=self.student,
            status=Submission.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )
        menu = prepare_update({"message": {"chat": {"id": 2002}, "from": {"id": 2002}, "text": "/menu"}})
        self.assertEqual(menu.kind, "menu")
        labels = [button["text"] for row in menu.markup["inline_keyboard"] for button in row]
        self.assertEqual(labels, ["На проверке", "Группы", "Сроки"])

        queue = prepare_update({"message": {"chat": {"id": 2002}, "from": {"id": 2002}, "text": "На проверке"}})
        self.assertEqual(queue.kind, "tqueue")
        self.assertIn(self.student.last_name, queue.text)
        self.assertIn("Эссе", queue.text)

        groups = prepare_update({"message": {"chat": {"id": 2002}, "from": {"id": 2002}, "text": "Группы"}})
        self.assertIn("EN A1", groups.text)

    def test_graded_work_is_not_accepted_again(self):
        Submission.objects.create(
            assignment=self.soon,
            student=self.student,
            status=Submission.Status.GRADED,
            score=90,
        )
        action = prepare_update(
            {
                "callback_query": {
                    "id": "cb4",
                    "data": "hwmenu",
                    "from": {"id": 1001},
                    "message": {"chat": {"id": 1001}},
                }
            }
        )
        labels = [row[0]["callback_data"] for row in action.markup["inline_keyboard"]]
        soon_day = timezone.localtime(self.soon.deadline).date().isoformat()
        self.assertNotIn(f"hwd:{soon_day}", labels)

    def test_uzbek_profile_gets_uzbek_menu(self):
        self.student.ui_language = "uz"
        self.student.save(update_fields=["ui_language"])
        menu = prepare_update({"message": {"chat": {"id": 1001}, "from": {"id": 1001}, "text": "/menu"}})
        labels = [button["text"] for row in menu.markup["inline_keyboard"] for button in row]
        self.assertEqual(labels, ["Uy vazifasini topshirish", "Ishlarim", "Muddatlar"])

        dates = prepare_update(
            {
                "callback_query": {
                    "id": "cb-uz",
                    "data": "hwmenu",
                    "from": {"id": 1001},
                    "message": {"chat": {"id": 1001}},
                }
            }
        )
        date_labels = [row[0]["text"] for row in dates.markup["inline_keyboard"]]
        self.assertIn("Muddatsiz · 1", date_labels)
        self.assertEqual(dates.text, "Topshirish sanasini tanlang.")

        deadlines = prepare_update({"message": {"chat": {"id": 1001}, "from": {"id": 1001}, "text": "Muddatlar"}})
        self.assertEqual(deadlines.kind, "deadlines")
        self.assertIn("Yaqin topshiriqlar:", deadlines.text)
