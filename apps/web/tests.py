from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.groups.models import Enrollment, Group, Language
from apps.homework.models import Assignment


class WebSmokeTests(TestCase):
    def test_landing(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_login_page(self):
        response = self.client.get(reverse("web:login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Демо-доступ")
        self.assertNotContains(response, "MaakCEOadmin")
        self.assertNotContains(response, "admin1dlc")
        self.assertNotContains(response, "Student123!")

    def test_login_lockout_after_repeated_failures(self):
        from django.core.cache import cache

        from apps.accounts.login_guard import MAX_PER_LOGIN

        cache.clear()
        User.objects.create_user(
            login="t.lockout",
            password="Teacher123!",
            role=User.Role.TEACHER,
            first_name="Лок",
            last_name="Тест",
            profile_completed=True,
        )
        for _ in range(MAX_PER_LOGIN):
            failed = self.client.post(reverse("web:login"), {"username": "t.lockout", "password": "nope"})
            self.assertContains(failed, "Неверный логин или пароль.")
        locked = self.client.post(reverse("web:login"), {"username": "t.lockout", "password": "Teacher123!"})
        self.assertContains(locked, "Слишком много попыток входа")

    def test_api_docs_require_login(self):
        self.assertIn(self.client.get("/api/docs/").status_code, {401, 403})
        self.assertIn(self.client.get("/api/schema/").status_code, {401, 403})

    def test_student_dashboard(self):
        user = User.objects.create_user(
            login="s.demo",
            password="Student123!",
            first_name="Демо",
            last_name="Ученик",
            role=User.Role.STUDENT,
        )
        self.client.login(username="s.demo", password="Student123!")
        response = self.client.get(reverse("web:dashboard"))
        self.assertContains(response, user.first_name)

    def test_homework_upload_for_teacher(self):
        teacher = User.objects.create_user(
            login="t.demo",
            password="Teacher123!",
            first_name="Мария",
            last_name="Иванова",
            role=User.Role.TEACHER,
        )
        language = Language.objects.create(code="en", name="English")
        group = Group.objects.create(name="B1 English", language=language, teacher=teacher)
        self.client.login(username="t.demo", password="Teacher123!")
        response = self.client.get(reverse("web:homework-create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Загрузить домашнее задание")
        self.assertContains(response, "attachments")

        create = self.client.post(
            reverse("web:homework-create"),
            {
                "title": "Unit 4 worksheet",
                "description": "Print and complete",
                "groups": group.pk,
                "is_published": "on",
                "attachments": SimpleUploadedFile("unit4.pdf", b"%PDF-1.4 demo", content_type="application/pdf"),
            },
        )
        self.assertEqual(create.status_code, 302)
        assignment = Assignment.objects.get(title="Unit 4 worksheet")
        self.assertEqual(assignment.files.count(), 1)
        self.assertEqual(assignment.files.first().original_name, "unit4.pdf")
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Группы")
        self.assertContains(home, "Ученики")
        self.assertContains(home, "Домашние задания")
        self.assertContains(home, "Посещаемость")
        self.assertNotContains(home, "Тесты")
        self.assertNotContains(home, "Упражнения")
        self.assertRedirects(self.client.get(reverse("web:tests")), reverse("web:homework"))
        self.assertRedirects(self.client.get(reverse("web:exercises")), reverse("web:homework"))

    def test_old_constructor_redirects_to_homework(self):
        User.objects.create_user(
            login="t.demo",
            password="Teacher123!",
            first_name="Мария",
            last_name="Иванова",
            role=User.Role.TEACHER,
        )
        self.client.login(username="t.demo", password="Teacher123!")
        response = self.client.get(reverse("web:test-create"))
        self.assertRedirects(response, reverse("web:homework-create"))

    def test_attendance_qr_and_student_checkin(self):
        teacher = User.objects.create_user(
            login="t.att",
            password="Teacher123!",
            first_name="Анна",
            last_name="Учитель",
            role=User.Role.TEACHER,
        )
        student = User.objects.create_user(
            login="s.att",
            password="Student123!",
            first_name="Олег",
            last_name="Ученик",
            role=User.Role.STUDENT,
        )
        language = Language.objects.create(code="en", name="English")
        group = Group.objects.create(name="B1 English", language=language, teacher=teacher)
        Enrollment.objects.create(student=student, group=group)
        self.client.login(username="t.att", password="Teacher123!")
        page = self.client.get(reverse("web:group-attendance", args=[group.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Копировать")
        self.assertContains(page, "/a/")
        from apps.attendance.models import Attendance, AttendanceSession

        session = AttendanceSession.objects.get(group=group, is_open=True)
        self.client.logout()
        self.client.login(username="s.att", password="Student123!")
        check = self.client.get(reverse("web:attendance-checkin", args=[session.token]))
        self.assertContains(check, "Вы на занятии")
        record = Attendance.objects.get(student=student, group=group)
        self.assertEqual(record.status, Attendance.Status.PRESENT)

    def test_student_first_login_requires_onboarding(self):
        student = User.objects.create_user(
            login="s.ru01",
            password="Student123!",
            role=User.Role.STUDENT,
            must_change_password=True,
            profile_completed=False,
        )
        self.client.login(username="s.ru01", password="Student123!")
        blocked = self.client.get(reverse("web:dashboard"))
        self.assertRedirects(blocked, reverse("web:onboarding"))
        page = self.client.get(reverse("web:onboarding"))
        self.assertContains(page, "Факультет")
        done = self.client.post(
            reverse("web:onboarding"),
            {
                "last_name": "Иванов",
                "first_name": "Пётр",
                "middle_name": "Сергеевич",
                "faculty": "Филологический",
                "course": "2",
                "password": "NewPass123!",
                "password2": "NewPass123!",
            },
        )
        self.assertRedirects(done, reverse("web:dashboard"))
        student.refresh_from_db()
        self.assertTrue(student.check_password("NewPass123!"))
        self.assertFalse(student.must_change_password)
        self.assertTrue(student.profile_completed)
        self.assertEqual(student.faculty, "Филологический")
        self.assertEqual(student.course, "2")
        self.assertEqual(student.full_name, "Иванов Пётр Сергеевич")

    def test_teacher_can_update_fio_photo_and_password(self):
        teacher = User.objects.create_user(
            login="t.sokolova",
            password="Sokolova1!",
            first_name="Анна",
            last_name="Соколова",
            role=User.Role.TEACHER,
        )
        self.client.login(username="t.sokolova", password="Sokolova1!")
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        response = self.client.post(
            reverse("web:profile"),
            {
                "last_name": "Соколова",
                "first_name": "Анна",
                "middle_name": "Игоревна",
                "phone": "+79990000000",
                "avatar": SimpleUploadedFile("photo.png", png, content_type="image/png"),
            },
        )
        self.assertRedirects(response, reverse("web:profile"))
        teacher.refresh_from_db()
        self.assertEqual(teacher.middle_name, "Игоревна")
        self.assertTrue(teacher.check_password("Sokolova1!"))
        self.assertTrue(bool(teacher.avatar))
        still_in = self.client.get(reverse("web:profile"))
        self.assertEqual(still_in.status_code, 200)
        self.assertNotContains(still_in, "Изменить пароль")

    def test_forgot_password_on_login_page(self):
        user = User.objects.create_user(
            login="s.reset",
            password="OldPass123!",
            first_name="Пётр",
            last_name="Иванов",
            phone="+998901112233",
            role=User.Role.STUDENT,
        )
        page = self.client.get(reverse("web:login"))
        self.assertContains(page, "Забыли пароль?")
        form = self.client.get(reverse("web:forgot-password"))
        self.assertEqual(form.status_code, 200)

        refused = self.client.post(
            reverse("web:forgot-password"),
            {
                "login": "s.reset",
                "last_name": "Иванов",
                "first_name": "Пётр",
                "phone": "000",
                "new_password": "NewPass123!",
                "new_password2": "NewPass123!",
            },
        )
        self.assertEqual(refused.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("OldPass123!"))

        changed = self.client.post(
            reverse("web:forgot-password"),
            {
                "login": "s.reset",
                "last_name": "Иванов",
                "first_name": "Пётр",
                "phone": "901112233",
                "new_password": "NewPass123!",
                "new_password2": "NewPass123!",
            },
        )
        self.assertRedirects(changed, reverse("web:login"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPass123!"))
        self.assertTrue(self.client.login(username="s.reset", password="NewPass123!"))

    def _class_setup(self):
        teacher = User.objects.create_user(
            login="t.flow",
            password="Teacher123!",
            first_name="Мария",
            last_name="Иванова",
            role=User.Role.TEACHER,
        )
        student = User.objects.create_user(
            login="s.flow",
            password="Student123!",
            first_name="Илья",
            last_name="Петров",
            role=User.Role.STUDENT,
        )
        outsider = User.objects.create_user(
            login="s.out",
            password="Student123!",
            first_name="Другой",
            last_name="Ученик",
            role=User.Role.STUDENT,
        )
        language = Language.objects.create(code="ru", name="Русский")
        group = Group.objects.create(name="Русский B1", language=language, teacher=teacher)
        Enrollment.objects.create(student=student, group=group)
        return teacher, student, outsider, group

    def test_homework_deadline_and_student_submit_review(self):
        from apps.homework.models import Submission

        teacher, student, outsider, group = self._class_setup()
        self.client.login(username="t.flow", password="Teacher123!")
        create = self.client.post(
            reverse("web:homework-create"),
            {
                "title": "Урок 3",
                "description": "Сделайте упражнения",
                "deadline": "2026-09-21T18:30",
                "groups": group.pk,
                "is_published": "on",
                "attachments": SimpleUploadedFile("lesson3.pdf", b"%PDF-1.4 work", content_type="application/pdf"),
            },
        )
        self.assertEqual(create.status_code, 302)
        assignment = Assignment.objects.get(title="Урок 3")
        self.assertIsNotNone(assignment.deadline)
        self.assertEqual(assignment.files.count(), 1)

        self.client.logout()
        self.client.login(username="s.out", password="Student123!")
        blocked = self.client.post(
            reverse("web:homework-submit", args=[assignment.pk]),
            {"answer": "не из этой группы"},
        )
        self.assertEqual(blocked.status_code, 403)

        self.client.logout()
        self.client.login(username="s.flow", password="Student123!")
        empty = self.client.post(reverse("web:homework-submit", args=[assignment.pk]), {})
        self.assertEqual(empty.status_code, 302)
        self.assertFalse(Submission.objects.filter(assignment=assignment, student=student).exists())

        sent = self.client.post(
            reverse("web:homework-submit", args=[assignment.pk]),
            {
                "answer": "готово",
                "files": [
                    SimpleUploadedFile("work.jpg", b"jpeg-bytes", content_type="image/jpeg"),
                    SimpleUploadedFile("page2.jpg", b"jpeg-bytes-2", content_type="image/jpeg"),
                ],
            },
        )
        self.assertEqual(sent.status_code, 302)
        submission = Submission.objects.get(assignment=assignment, student=student)
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        self.assertEqual(submission.files.count(), 2)

        self.client.logout()
        self.client.login(username="t.flow", password="Teacher123!")
        returned = self.client.post(
            reverse("web:submission-review", args=[submission.pk]),
            {"return_for_revision": "1", "feedback": "добавьте фото"},
        )
        self.assertEqual(returned.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.RETURNED)
        self.assertIsNone(submission.score)

        grade = self.client.post(
            reverse("web:submission-review", args=[submission.pk]),
            {"score": "87", "feedback": "хорошо"},
        )
        self.assertEqual(grade.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.GRADED)
        self.assertEqual(submission.score, 87)

    def test_attendance_qr_survives_partial_save(self):
        from apps.attendance.models import Attendance, AttendanceSession

        teacher, student, outsider, group = self._class_setup()
        self.client.login(username="t.flow", password="Teacher123!")
        page = self.client.get(reverse("web:group-attendance", args=[group.pk]))
        self.assertEqual(page.status_code, 200)
        session = AttendanceSession.objects.get(group=group, is_open=True)
        self.client.logout()
        self.client.login(username="s.flow", password="Student123!")
        check = self.client.get(reverse("web:attendance-checkin", args=[session.token]))
        self.assertContains(check, "Вы на занятии")
        record = Attendance.objects.get(student=student, group=group)
        self.assertEqual(record.status, Attendance.Status.PRESENT)

        self.client.logout()
        self.client.login(username="t.flow", password="Teacher123!")
        save = self.client.post(
            reverse("web:group-attendance", args=[group.pk]),
            {"action": "save", "lesson_date": record.lesson_date.isoformat()},
        )
        self.assertEqual(save.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.status, Attendance.Status.PRESENT)

        export = self.client.get(reverse("web:export-attendance", args=[group.pk]))
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheet", export["Content-Type"])
        from io import BytesIO
        from openpyxl import load_workbook

        book = load_workbook(BytesIO(export.content))
        sheet = book["Занятия"]
        names = [sheet.cell(row, 2).value for row in range(4, sheet.max_row + 1)]
        self.assertEqual(names, [student.last_name])
        self.assertNotIn(outsider.last_name, names)
        self.assertEqual(sheet.cell(4, 5).value, "+")
        self.assertIn("filename*=UTF-8''", export["Content-Disposition"])

    def test_attendance_excel_keeps_other_groups_out(self):
        from datetime import date
        from io import BytesIO

        from openpyxl import load_workbook

        from apps.attendance.models import Attendance, LectureAttendance, LectureSession, LectureStream

        teacher, student, outsider, group = self._class_setup()
        other = Group.objects.create(name="Другая группа", language=group.language, teacher=teacher)
        Enrollment.objects.create(student=outsider, group=other)
        Attendance.objects.create(
            student=student,
            group=group,
            lesson_date=date(2026, 9, 10),
            kind=Attendance.Kind.CLASS,
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            student=outsider,
            group=other,
            lesson_date=date(2026, 9, 10),
            kind=Attendance.Kind.CLASS,
            status=Attendance.Status.ABSENT,
        )
        stream = LectureStream.objects.create(name="Общий поток", lector=teacher)
        stream.groups.add(group, other)
        session = LectureSession.objects.create(stream=stream, date=date(2026, 9, 12), topic="Тема")
        LectureAttendance.objects.create(session=session, student=student, status=LectureAttendance.Status.PRESENT)
        LectureAttendance.objects.create(session=session, student=outsider, status=LectureAttendance.Status.PRESENT)

        self.client.login(username="t.flow", password="Teacher123!")
        export = self.client.get(reverse("web:export-attendance", args=[group.pk]))
        book = load_workbook(BytesIO(export.content))
        self.assertEqual(book.sheetnames, ["Занятия", "Лекции"])
        class_names = [book["Занятия"].cell(row, 2).value for row in range(4, book["Занятия"].max_row + 1)]
        lecture_names = [book["Лекции"].cell(row, 2).value for row in range(4, book["Лекции"].max_row + 1)]
        self.assertEqual(class_names, [student.last_name])
        self.assertEqual(lecture_names, [student.last_name])
        self.assertEqual(book["Лекции"].cell(4, 5).value, "+")
        self.assertEqual(book["Занятия"].cell(4, 9).value, 100.0)

    def test_teacher_sees_student_performance(self):
        from apps.homework.models import Submission

        teacher, student, outsider, group = self._class_setup()
        assignment = Assignment.objects.create(title="Контрольная", group=group, is_published=True, created_by=teacher)
        Submission.objects.create(assignment=assignment, student=student, status=Submission.Status.GRADED, score=81)
        self.client.login(username="t.flow", password="Teacher123!")
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Успеваемость")
        self.assertContains(home, student.last_name)
        self.assertContains(home, "81")
        roster = self.client.get(reverse("web:progress"))
        self.assertContains(roster, student.full_name)
        self.assertContains(roster, "81")
        self.assertContains(roster, "classScoreChart")
        card = self.client.get(reverse("web:student-analytics", args=[student.pk]))
        self.assertContains(card, "Средний балл")
        self.assertContains(card, "81")
        self.assertContains(card, assignment.title)
        self.assertContains(card, "scoreChart")
        self.assertContains(card, "Динамика оценок")
        blocked = self.client.get(reverse("web:student-analytics", args=[outsider.pk]))
        self.assertEqual(blocked.status_code, 404)

    def _admin(self):
        return User.objects.create_user(
            login="admin",
            password="Admin123!",
            first_name="Алина",
            last_name="Админ",
            role=User.Role.ADMIN,
            is_staff=True,
        )

    def test_admin_creates_teacher_with_login_password(self):
        self._admin()
        self.client.login(username="admin", password="Admin123!")
        page = self.client.get(reverse("web:teacher-create"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Логин")
        created = self.client.post(
            reverse("web:teacher-create"),
            {
                "last_name": "Белова",
                "first_name": "Ирина",
                "middle_name": "",
                "login": "t.belova",
                "password": "Cabin7!light",
                "password2": "Cabin7!light",
                "phone": "",
                "notes": "",
            },
        )
        self.assertEqual(created.status_code, 302)
        teacher = User.objects.get(login="t.belova")
        self.assertTrue(teacher.is_teacher)
        self.assertTrue(teacher.check_password("Cabin7!light"))
        self.client.logout()
        self.assertTrue(self.client.login(username="t.belova", password="Cabin7!light"))

    def test_admin_creates_student_in_teacher_group(self):
        self._admin()
        teacher = User.objects.create_user(
            login="t.host",
            password="Teacher123!",
            first_name="Мария",
            last_name="Хостова",
            role=User.Role.TEACHER,
        )
        other = User.objects.create_user(
            login="t.other",
            password="Teacher123!",
            first_name="Олег",
            last_name="Другой",
            role=User.Role.TEACHER,
        )
        language = Language.objects.create(code="ru", name="Русский")
        group = Group.objects.create(name="Русский A1", language=language, teacher=teacher)
        other_group = Group.objects.create(name="Русский B1", language=language, teacher=other)
        self.client.login(username="admin", password="Admin123!")
        page = self.client.get(reverse("web:student-create"))
        self.assertContains(page, "Преподаватель")
        created = self.client.post(
            reverse("web:student-create"),
            {
                "last_name": "",
                "first_name": "",
                "login": "s.novikov",
                "password": "Student123!",
                "password2": "Student123!",
                "teacher": teacher.pk,
                "group": group.pk,
            },
        )
        self.assertEqual(created.status_code, 302)
        student = User.objects.get(login="s.novikov")
        self.assertTrue(student.is_student)
        self.assertTrue(student.must_change_password)
        self.assertFalse(student.profile_completed)
        self.assertTrue(Enrollment.objects.filter(student=student, group=group).exists())

        mismatch = self.client.post(
            reverse("web:student-create"),
            {
                "login": "s.wrong",
                "password": "Student123!",
                "password2": "Student123!",
                "teacher": teacher.pk,
                "group": other_group.pk,
            },
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertFalse(User.objects.filter(login="s.wrong").exists())

        moved = self.client.post(
            reverse("web:user-edit", args=[student.pk]),
            {
                "last_name": student.last_name,
                "first_name": student.first_name,
                "middle_name": "",
                "login": student.login,
                "role": User.Role.STUDENT,
                "phone": "",
                "faculty": "",
                "course": "",
                "notes": "",
                "is_active": "on",
                "groups": [other_group.pk],
            },
        )
        self.assertEqual(moved.status_code, 302)
        self.assertTrue(Enrollment.objects.filter(student=student, group=other_group).exists())
        self.assertFalse(Enrollment.objects.filter(student=student, group=group).exists())

    def test_teacher_cannot_create_accounts(self):
        User.objects.create_user(
            login="t.nope",
            password="Teacher123!",
            first_name="Нет",
            last_name="Прав",
            role=User.Role.TEACHER,
        )
        self.client.login(username="t.nope", password="Teacher123!")
        self.assertEqual(self.client.get(reverse("web:teacher-create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:lector-create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:student-create")).status_code, 403)

    def test_staff_cannot_review_other_group_homework(self):
        from apps.homework.models import Submission

        teacher_a, student_a, _outsider, group_a = self._class_setup()
        teacher_b = User.objects.create_user(
            login="t.otherteach",
            password="Teacher123!",
            first_name="Олег",
            last_name="Другов",
            role=User.Role.TEACHER,
        )
        assistant = User.objects.create_user(
            login="a.flow",
            password="Assist123!",
            first_name="Полина",
            last_name="Крылова",
            role=User.Role.ASSISTANT,
            lead_teacher=teacher_a,
        )
        language = group_a.language
        group_b = Group.objects.create(name="Чужая группа", language=language, teacher=teacher_b)
        student_b = User.objects.create_user(
            login="s.othergroup",
            password="Student123!",
            first_name="Ника",
            last_name="Чужая",
            role=User.Role.STUDENT,
        )
        Enrollment.objects.create(student=student_b, group=group_b)
        work_a = Assignment.objects.create(title="ДЗ группы А", group=group_a, is_published=True, created_by=teacher_a)
        work_b = Assignment.objects.create(title="ДЗ группы Б", group=group_b, is_published=True, created_by=teacher_b)
        sub_a = Submission.objects.create(assignment=work_a, student=student_a, status=Submission.Status.SUBMITTED)
        sub_b = Submission.objects.create(assignment=work_b, student=student_b, status=Submission.Status.SUBMITTED)

        self.client.login(username="t.flow", password="Teacher123!")
        self.assertEqual(self.client.get(reverse("web:submission-review", args=[sub_a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("web:submission-review", args=[sub_b.pk])).status_code, 403)
        own_students = self.client.get(reverse("web:students"))
        self.assertContains(own_students, student_a.last_name)
        self.assertNotContains(own_students, student_b.last_name)

        self.client.logout()
        self.client.login(username="a.flow", password="Assist123!")
        self.assertEqual(self.client.get(reverse("web:submission-review", args=[sub_a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("web:submission-review", args=[sub_b.pk])).status_code, 403)
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Ассистент")
        self.assertContains(home, group_a.name)
        self.assertNotContains(home, group_b.name)
        self.assertTrue(assistant.is_assistant)
        self.assertTrue(assistant.is_teaching_staff)

    def test_teacher_and_assistant_cannot_review_same_work(self):
        from datetime import timedelta

        from django.test import Client
        from django.utils import timezone

        from apps.homework.models import Submission

        teacher, student, _outsider, group = self._class_setup()
        assistant = User.objects.create_user(
            login="a.lock",
            password="Assist123!",
            first_name="Полина",
            last_name="Крылова",
            role=User.Role.ASSISTANT,
            lead_teacher=teacher,
        )
        work = Assignment.objects.create(title="Сочинение", group=group, is_published=True, created_by=teacher)
        submission = Submission.objects.create(
            assignment=work,
            student=student,
            status=Submission.Status.SUBMITTED,
            answer="мой текст",
        )
        self.assertEqual(submission.review_state, "pending")

        teacher_client = self.client
        teacher_client.login(username="t.flow", password="Teacher123!")
        board = teacher_client.get(reverse("web:homework-detail", args=[work.pk]))
        self.assertContains(board, "review-row pending")
        self.assertContains(board, "Не проверено")

        opened = teacher_client.get(reverse("web:submission-review", args=[submission.pk]))
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, "Вы проверяете эту работу")
        submission.refresh_from_db()
        self.assertEqual(submission.review_state, "checking")
        self.assertEqual(submission.reviewing_by_id, teacher.pk)

        assist_client = Client()
        assist_client.login(username="a.lock", password="Assist123!")
        locked_page = assist_client.get(reverse("web:submission-review", args=[submission.pk]))
        self.assertEqual(locked_page.status_code, 200)
        self.assertContains(locked_page, "Сейчас проверяет")
        self.assertContains(locked_page, teacher.last_name)
        self.assertContains(locked_page, 'disabled')
        steal = assist_client.post(
            reverse("web:submission-review", args=[submission.pk]),
            {"score": "90", "feedback": "ок"},
        )
        self.assertEqual(steal.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        self.assertIsNone(submission.score)

        board_assist = assist_client.get(reverse("web:homework-detail", args=[work.pk]))
        self.assertContains(board_assist, "review-row checking")
        self.assertContains(board_assist, "Проверяет")

        ping = teacher_client.post(reverse("web:submission-review-lock", args=[submission.pk]), {"action": "ping"})
        self.assertEqual(ping.status_code, 200)
        blocked_ping = assist_client.post(reverse("web:submission-review-lock", args=[submission.pk]), {"action": "ping"})
        self.assertEqual(blocked_ping.status_code, 409)

        grade = teacher_client.post(
            reverse("web:submission-review", args=[submission.pk]),
            {"score": "88", "feedback": "хорошо"},
        )
        self.assertEqual(grade.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.GRADED)
        self.assertEqual(submission.review_state, "done")
        self.assertIsNone(submission.reviewing_by_id)

        done_board = assist_client.get(reverse("web:homework-detail", args=[work.pk]))
        self.assertContains(done_board, "review-row done")
        self.assertContains(done_board, "Проверено")

        other = Submission.objects.create(
            assignment=work,
            student=User.objects.create_user(
                login="s.lock2",
                password="Student123!",
                first_name="Лена",
                last_name="Серова",
                role=User.Role.STUDENT,
            ),
            status=Submission.Status.SUBMITTED,
        )
        other.reviewing_by = teacher
        other.reviewing_at = timezone.now() - timedelta(seconds=120)
        other.save()
        self.assertFalse(other.lock_active())
        take = assist_client.get(reverse("web:submission-review", args=[other.pk]))
        self.assertContains(take, "Вы проверяете эту работу")
        other.refresh_from_db()
        self.assertEqual(other.reviewing_by_id, assistant.pk)

        teacher_client.post(reverse("web:submission-review-lock", args=[other.pk]), {"action": "ping"})
        other.refresh_from_db()
        self.assertEqual(other.reviewing_by_id, assistant.pk)
        assist_client.post(reverse("web:submission-review-lock", args=[other.pk]), {"action": "release"})
        other.refresh_from_db()
        self.assertIsNone(other.reviewing_by_id)
        self.assertEqual(other.review_state, "pending")

    def test_submission_review_survives_bad_answers_json(self):
        from apps.homework.models import Submission

        teacher, student, _outsider, group = self._class_setup()
        work = Assignment.objects.create(title="Лист", group=group, is_published=True, created_by=teacher)
        submission = Submission.objects.create(
            assignment=work,
            student=student,
            status=Submission.Status.SUBMITTED,
            answer="только текст",
        )
        Submission.objects.filter(pk=submission.pk).update(answers=[])
        self.client.login(username="t.flow", password="Teacher123!")
        page = self.client.get(reverse("web:submission-review", args=[submission.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "только текст")

    def test_primary_admin_manages_secondary_and_sees_actions(self):
        from apps.accounts.bootstrap import (
            PRIMARY_ADMIN_LOGIN,
            PRIMARY_ADMIN_PASSWORD,
            SECONDARY_ADMIN_LOGIN,
            SECONDARY_ADMIN_PASSWORD,
            ensure_platform_admins,
        )
        from apps.audit.models import AuditLog

        primary, secondary = ensure_platform_admins()
        self.assertTrue(primary.is_primary_admin)
        self.assertTrue(secondary.is_admin)
        self.assertFalse(secondary.is_primary_admin)
        self.assertTrue(self.client.login(username=PRIMARY_ADMIN_LOGIN, password=PRIMARY_ADMIN_PASSWORD))
        self.assertTrue(self.client.login(username="maakceoadmin", password=PRIMARY_ADMIN_PASSWORD))

        page = self.client.get(reverse("web:admins"))
        self.assertContains(page, SECONDARY_ADMIN_LOGIN)
        created = self.client.post(
            reverse("web:admin-create"),
            {
                "last_name": "Козлова",
                "first_name": "Елена",
                "login": "AdminExtra",
                "password": "NorthStar9!q",
                "password2": "NorthStar9!q",
            },
        )
        self.assertEqual(created.status_code, 302)
        extra = User.objects.get(login="AdminExtra")
        self.assertTrue(extra.is_admin)
        self.assertFalse(extra.is_primary_admin)

        self.client.logout()
        self.client.login(username=SECONDARY_ADMIN_LOGIN, password=SECONDARY_ADMIN_PASSWORD)
        self.assertEqual(self.client.get(reverse("web:admins")).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:audit")).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:admin-create")).status_code, 403)
        blocked = self.client.post(
            reverse("web:admin-create"),
            {
                "last_name": "Хакеров",
                "first_name": "Нет",
                "login": "admin.hack",
                "password": "HackerAdmin9$",
                "password2": "HackerAdmin9$",
            },
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(User.objects.filter(login="admin.hack").exists())

        teacher = self.client.post(
            reverse("web:teacher-create"),
            {
                "last_name": "Белова",
                "first_name": "Ирина",
                "login": "t.stafflog",
                "password": "Cabin7!light",
                "password2": "Cabin7!light",
            },
        )
        self.assertEqual(teacher.status_code, 302)
        self.assertTrue(
            AuditLog.objects.filter(actor=secondary, action="Создал преподавателя").exists()
        )

        self.client.logout()
        self.client.login(username=PRIMARY_ADMIN_LOGIN, password=PRIMARY_ADMIN_PASSWORD)
        journal = self.client.get(reverse("web:audit"))
        self.assertContains(journal, SECONDARY_ADMIN_LOGIN)
        self.assertContains(journal, "Создал преподавателя")
        self.assertContains(journal, "t.stafflog")
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Что сделали администраторы")
        self.assertContains(home, "Создал преподавателя")


    def test_admin_creates_lector_stream_lecture_attendance(self):
        from datetime import date

        from apps.attendance.models import Attendance, LectureAttendance, LectureSession, LectureStream
        from apps.core.metrics import attendance_percent

        self._admin()
        teacher, student, _outsider, group = self._class_setup()
        other_teacher = User.objects.create_user(
            login="t.second",
            password="Teacher123!",
            first_name="Олег",
            last_name="Второй",
            role=User.Role.TEACHER,
        )
        other_group = Group.objects.create(name="МЭО2", language=group.language, teacher=other_teacher)
        foreign_group = Group.objects.create(name="Чужая", language=group.language, teacher=other_teacher)
        other_student = User.objects.create_user(
            login="s.lecture",
            password="Student123!",
            first_name="Алина",
            last_name="Лекционная",
            role=User.Role.STUDENT,
        )
        foreign_student = User.objects.create_user(
            login="s.foreign",
            password="Student123!",
            first_name="Чужой",
            last_name="Поток",
            role=User.Role.STUDENT,
        )
        Enrollment.objects.create(student=other_student, group=other_group)
        Enrollment.objects.create(student=foreign_student, group=foreign_group)
        self.client.login(username="admin", password="Admin123!")
        created = self.client.post(
            reverse("web:lector-create"),
            {
                "last_name": "Орлова",
                "first_name": "Елена",
                "middle_name": "",
                "login": "l.orlova",
                "password": "Lector123!",
                "password2": "Lector123!",
                "phone": "",
                "notes": "",
            },
        )
        self.assertEqual(created.status_code, 302)
        lector = User.objects.get(login="l.orlova")
        stream = LectureStream.objects.create(name="Общий поток", lector=lector)
        stream.groups.set([group.pk, other_group.pk])
        session = LectureSession.objects.create(stream=stream, date=date(2026, 9, 28), topic="Введение")
        self.client.logout()
        self.assertTrue(self.client.login(username="l.orlova", password="Lector123!"))
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Лектор")
        self.assertContains(home, group.name)
        self.assertContains(home, other_group.name)
        self.assertNotContains(home, foreign_group.name)
        page = self.client.get(
            reverse("web:lecture-attendance"),
            {"stream": stream.pk, "date": session.date.isoformat()},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, student.last_name)
        self.assertContains(page, other_student.last_name)
        self.assertNotContains(page, foreign_student.full_name)
        save = self.client.post(
            reverse("web:lecture-attendance"),
            {
                "stream_id": stream.pk,
                "lesson_date": session.date.isoformat(),
                f"status_{student.pk}": "present",
                f"status_{other_student.pk}": "absent",
            },
        )
        self.assertEqual(save.status_code, 302)
        self.assertTrue(
            LectureAttendance.objects.filter(
                session=session, student=student, status=LectureAttendance.Status.PRESENT
            ).exists()
        )
        self.assertTrue(
            LectureAttendance.objects.filter(
                session=session, student=other_student, status=LectureAttendance.Status.ABSENT
            ).exists()
        )
        Attendance.objects.update_or_create(
            student=student,
            group=group,
            lesson_date=date(2026, 9, 28),
            kind=Attendance.Kind.CLASS,
            defaults={"status": Attendance.Status.PRESENT, "marked_by": teacher},
        )
        percent = attendance_percent(student, group)
        self.assertIsNotNone(percent)
        self.assertGreater(percent, 0)
        self.assertEqual(self.client.get(reverse("web:group-attendance", args=[other_group.pk])).status_code, 403)

    def test_teacher_assigns_homework_to_several_groups(self):
        teacher, student, _outsider, group = self._class_setup()
        second = Group.objects.create(name="МЭО2", language=group.language, teacher=teacher)
        other_teacher = User.objects.create_user(
            login="t.notmine",
            password="Teacher123!",
            first_name="Чужой",
            last_name="Учитель",
            role=User.Role.TEACHER,
        )
        foreign = Group.objects.create(name="Чужая", language=group.language, teacher=other_teacher)
        self.client.login(username="t.flow", password="Teacher123!")
        page = self.client.get(reverse("web:homework-create"))
        self.assertContains(page, "Все группы")
        self.assertContains(page, group.name)
        self.assertContains(page, second.name)
        self.assertNotContains(page, foreign.name)
        created = self.client.post(
            reverse("web:homework-create"),
            {
                "title": "Общее ДЗ",
                "description": "Для нескольких групп",
                "groups": [group.pk, second.pk],
                "is_published": "on",
            },
        )
        self.assertEqual(created.status_code, 302)
        works = Assignment.objects.filter(title="Общее ДЗ")
        self.assertEqual(works.count(), 2)
        self.assertEqual(set(works.values_list("group_id", flat=True)), {group.pk, second.pk})
        blocked = self.client.post(
            reverse("web:homework-create"),
            {
                "title": "Чужое ДЗ",
                "groups": [foreign.pk],
                "is_published": "on",
            },
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertFalse(Assignment.objects.filter(title="Чужое ДЗ").exists())

    def test_teacher_cannot_open_lecture_attendance(self):
        User.objects.create_user(
            login="t.nolc",
            password="Teacher123!",
            first_name="Нет",
            last_name="Лекций",
            role=User.Role.TEACHER,
        )
        self.client.login(username="t.nolc", password="Teacher123!")
        self.assertEqual(self.client.get(reverse("web:lecture-attendance")).status_code, 403)

    def test_teacher_assigned_to_lecture_stream_can_mark_attendance(self):
        from datetime import date

        from apps.attendance.models import LectureSession, LectureStream

        teacher, student, _outsider, group = self._class_setup()
        stream = LectureStream.objects.create(name="МЭО · общая", lector=teacher)
        stream.groups.set([group.pk])
        self.client.login(username=teacher.login, password="Teacher123!")
        page = self.client.get(
            reverse("web:lecture-attendance"),
            {"stream": stream.pk, "date": "2026-09-28"},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, student.last_name)
        saved = self.client.post(
            reverse("web:lecture-attendance"),
            {
                "stream_id": stream.pk,
                "lesson_date": "2026-09-28",
                f"status_{student.pk}": "present",
            },
        )
        self.assertEqual(saved.status_code, 302)
        self.assertTrue(LectureSession.objects.filter(stream=stream, date=date(2026, 9, 28)).exists())
        group_page = self.client.get(reverse("web:group-attendance", args=[group.pk]))
        self.assertEqual(group_page.status_code, 200)

    def test_attendance_shows_only_selected_group(self):
        teacher, student, outsider, group = self._class_setup()
        language = group.language
        other = Group.objects.create(name="Другая группа", language=language, teacher=teacher)
        Enrollment.objects.create(student=outsider, group=other)
        from apps.attendance.models import LectureStream

        stream = LectureStream.objects.create(name="Общий поток", lector=teacher)
        stream.groups.set([group.pk, other.pk])
        self.client.login(username="t.flow", password="Teacher123!")

        own = self.client.get(reverse("web:group-attendance", args=[group.pk]))
        self.assertContains(own, student.last_name)
        self.assertNotContains(own, "Другой")
        self.assertContains(own, other.name)

        lecture = self.client.get(reverse("web:lecture-attendance"), {"stream": stream.pk, "date": "2026-10-06"})
        self.assertContains(lecture, "Выберите группу")
        self.assertNotContains(lecture, student.last_name)
        picked = self.client.get(
            reverse("web:lecture-attendance"),
            {"stream": stream.pk, "date": "2026-10-06", "group": group.pk},
        )
        self.assertContains(picked, student.last_name)
        self.assertNotContains(picked, "Другой")


    def test_edit_attendance_date_and_homework_deadline(self):
        from datetime import date

        from apps.attendance.models import Attendance, AttendanceSession

        teacher, student, _outsider, group = self._class_setup()
        lesson = date(2026, 9, 10)
        Attendance.objects.create(
            student=student,
            group=group,
            lesson_date=lesson,
            status=Attendance.Status.PRESENT,
            marked_by=teacher,
        )
        AttendanceSession.objects.create(group=group, lesson_date=lesson, token="MOVE0001", created_by=teacher)
        assignment = Assignment.objects.create(
            title="Урок 4",
            group=group,
            created_by=teacher,
            is_published=True,
        )
        self.client.login(username="t.flow", password="Teacher123!")
        page = self.client.get(reverse("web:group-attendance", args=[group.pk]) + "?date=2026-09-10")
        self.assertContains(page, "Сохранённые")
        self.assertContains(page, "10.09.2026")
        self.assertContains(page, student.last_name)

        moved = self.client.post(
            reverse("web:group-attendance", args=[group.pk]),
            {"action": "move", "lesson_date": "2026-09-10", "new_date": "2026-09-12"},
        )
        self.assertEqual(moved.status_code, 302)
        record = Attendance.objects.get(student=student, group=group)
        self.assertEqual(record.lesson_date, date(2026, 9, 12))
        self.assertEqual(AttendanceSession.objects.get(token="MOVE0001").lesson_date, date(2026, 9, 12))

        blocked = self.client.post(
            reverse("web:group-attendance", args=[group.pk]),
            {"action": "move", "lesson_date": "2026-09-12", "new_date": "2026-09-12"},
        )
        self.assertEqual(blocked.status_code, 302)
        Attendance.objects.create(
            student=student,
            group=group,
            lesson_date=date(2026, 9, 15),
            status=Attendance.Status.ABSENT,
            marked_by=teacher,
        )
        clash = self.client.post(
            reverse("web:group-attendance", args=[group.pk]),
            {"action": "move", "lesson_date": "2026-09-12", "new_date": "2026-09-15"},
        )
        self.assertEqual(clash.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.lesson_date, date(2026, 9, 12))

        cleared = self.client.post(
            reverse("web:group-attendance", args=[group.pk]),
            {"action": "save", "lesson_date": "2026-09-12", f"status_{student.pk}": "clear"},
        )
        self.assertEqual(cleared.status_code, 302)
        self.assertFalse(Attendance.objects.filter(student=student, group=group, lesson_date=date(2026, 9, 12)).exists())

        saved = self.client.post(
            reverse("web:homework-detail", args=[assignment.pk]),
            {"action": "deadline", "deadline": "2026-10-02T18:00", "next": reverse("web:homework")},
        )
        self.assertRedirects(saved, reverse("web:homework"))
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.deadline)
        from django.utils import timezone

        self.assertEqual(timezone.localtime(assignment.deadline).hour, 18)
        self.assertEqual(timezone.localtime(assignment.deadline).minute, 0)

        self.client.logout()
        self.client.login(username="s.flow", password="Student123!")
        denied = self.client.post(
            reverse("web:homework-detail", args=[assignment.pk]),
            {"action": "deadline", "deadline": "2026-10-03T18:00"},
        )
        self.assertEqual(denied.status_code, 403)


class LanguageSwitchTests(TestCase):
    def test_landing_has_switcher_and_uzbek_copy(self):
        page = self.client.get("/")
        self.assertContains(page, 'value="uz"')
        self.assertContains(page, "Кабинет, который светится вместе с занятием.")
        switched = self.client.post(reverse("web:set-language"), {"language": "uz", "next": "/"}, follow=True)
        self.assertEqual(self.client.cookies["aula_language"].value, "uz")
        self.assertContains(switched, "Dars bilan birga yonadigan kabinet.")
        self.assertNotContains(switched, "Кабинет, который светится вместе с занятием.")

    def test_lecture_streams_page_switches_to_uzbek(self):
        admin = User.objects.create_user(
            login="admin.uzlec",
            password="Admin123!",
            first_name="Admin",
            last_name="Uz",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        admin.is_primary_admin = True
        admin.save(update_fields=["is_primary_admin"])
        self.client.login(username="admin.uzlec", password="Admin123!")
        self.client.post(reverse("web:set-language"), {"language": "uz", "next": reverse("web:lecture-streams")})
        page = self.client.get(reverse("web:lecture-streams"))
        self.assertContains(page, "Ma’ruza oqimlari")
        self.assertContains(page, "Yangi oqim")
        self.assertNotContains(page, "Потоки лекций")

    def test_teacher_nav_switches_to_uzbek(self):
        teacher = User.objects.create_user(
            login="t.lang",
            password="Teacher123!",
            first_name="Мария",
            last_name="Иванова",
            role=User.Role.TEACHER,
        )
        self.client.login(username="t.lang", password="Teacher123!")
        self.client.post(reverse("web:set-language"), {"language": "uz", "next": reverse("web:dashboard")})
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Guruhlar")
        self.assertContains(home, "Uy vazifalari")
        self.assertContains(home, "O‘qituvchi kabineti")
        teacher.refresh_from_db()
        self.assertEqual(teacher.ui_language, "uz")

    def test_login_restores_saved_ui_language(self):
        User.objects.create_user(
            login="t.lang2",
            password="Teacher123!",
            first_name="Иван",
            last_name="Петров",
            role=User.Role.TEACHER,
            ui_language="uz",
        )
        self.client.post(reverse("web:login"), {"username": "t.lang2", "password": "Teacher123!"})
        home = self.client.get(reverse("web:dashboard"))
        self.assertContains(home, "Guruhlar")
        self.assertContains(home, "Uy vazifalari")



