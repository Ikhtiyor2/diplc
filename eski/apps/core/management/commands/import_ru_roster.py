from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from openpyxl import Workbook, load_workbook

from apps.accounts.models import User
from apps.core.credentials import generate_login, generate_password
from apps.groups.models import Enrollment, Group, Language

MASTER_SHEETS = ("Русский язык МЭО", "Русский язык МО")
DEMO_TEACHER_LOGINS = ("t.sokolova", "t.volkov", "t.morozova", "t.kuznetsov")
DEMO_ASSISTANT_LOGINS = ("a.krylova", "a.belov", "a.orlova", "a.sergeeva")

SCHEDULES = {
    "МЭО1": "Пн / Ср 07:30",
    "МЭО2": "Пн / Ср 07:30",
    "МЭО3": "Пн / Ср 09:00",
    "МЭО4": "Пн / Ср 09:00",
    "МЭО5": "Вт / Чт 07:30",
    "МЭО6": "Вт / Чт 07:30",
    "МЭО7": "Вт / Чт 09:00",
    "МЭО8": "Вт / Чт 09:00",
    "МП1": "Пн / Ср 20:00",
    "МО1": "Пн / Ср 20:00",
    "МО2": "Пн / Ср 21:30",
    "МО3": "Пн / Ср 21:30",
    "МО4": "Вт / Чт 20:00",
    "МО5": "Вт / Чт 20:00",
    "МО6": "Вт / Чт 21:30",
    "Аралаш": "по расписанию",
}


def _cell(value) -> str:
    return str(value).strip() if value is not None else ""


def split_fio(fio: str) -> tuple[str, str, str]:
    cleaned = re.sub(r"\([^)]*\)", "", " ".join(fio.replace("\n", " ").split())).strip()
    parts = cleaned.split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], " ".join(parts[2:])


def parse_roster(path: Path) -> list[dict]:
    wb = load_workbook(path, data_only=True)
    missing = [name for name in MASTER_SHEETS if name not in wb.sheetnames]
    if missing:
        raise CommandError(f"В файле нет листов: {', '.join(missing)}")
    rows = []
    for sheet_name in MASTER_SHEETS:
        ws = wb[sheet_name]
        for index, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if index == 1:
                continue
            fio = _cell(row[1] if len(row) > 1 else "")
            if not fio:
                continue
            last_name, first_name, middle_name = split_fio(fio)
            rows.append(
                {
                    "fio": fio,
                    "last_name": last_name,
                    "first_name": first_name,
                    "middle_name": middle_name,
                    "faculty": _cell(row[2] if len(row) > 2 else ""),
                    "phone": _cell(row[3] if len(row) > 3 else ""),
                    "teacher": _cell(row[4] if len(row) > 4 else ""),
                    "assistant": _cell(row[5] if len(row) > 5 else ""),
                    "group": _cell(row[6] if len(row) > 6 else ""),
                }
            )
    return rows


def _write_sheet(wb: Workbook, title: str, rows: list[tuple]):
    ws = wb.create_sheet(title)
    ws.append(("Роль", "ФИО", "Логин", "Пароль", "Группа", "Факультет"))
    for row in rows:
        ws.append(row)


class Command(BaseCommand):
    help = "Импортирует учителей, ассистентов, группы и учеников русского языка из Umumiy ro'yhat"

    def add_arguments(self, parser):
        parser.add_argument("--file", dest="path")

    def handle(self, *args, **options):
        path = Path(options["path"]) if options.get("path") else self._default_file()
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")

        rows = parse_roster(path)
        language, _ = Language.objects.get_or_create(
            code="ru",
            defaults={"name": "Русский", "native_name": "Русский", "flag": "🇷🇺"},
        )

        teachers = {}
        assistants = {}
        groups = {}
        issued = {"teachers": [], "assistants": [], "students": []}

        staff_pairs = {(row["teacher"], row["assistant"]) for row in rows if row["teacher"]}
        for teacher_name, assistant_name in sorted(staff_pairs):
            teacher, teacher_password = self._upsert_staff(
                first_name=teacher_name,
                role=User.Role.TEACHER,
            )
            teachers[teacher_name] = teacher
            if teacher_password:
                issued["teachers"].append(("Преподаватель", teacher_name, teacher.login, teacher_password, "", ""))
            if assistant_name:
                assistant, assistant_password = self._upsert_staff(
                    first_name=assistant_name,
                    role=User.Role.ASSISTANT,
                    lead_teacher=teacher,
                )
                assistants[assistant_name] = assistant
                if assistant_password:
                    issued["assistants"].append(
                        ("Ассистент", assistant_name, assistant.login, assistant_password, "", "")
                    )

        for group_name in sorted({row["group"] for row in rows if row["group"]}):
            sample = next(row for row in rows if row["group"] == group_name)
            teacher = teachers[sample["teacher"]]
            groups[group_name] = self._upsert_group(group_name, language, teacher)

        seen_students: dict[str, User] = {}
        for row in rows:
            key = f"ru_roster|{row['group']}|{row['fio']}"
            if key in seen_students:
                student = seen_students[key]
            else:
                student, password = self._upsert_student(row, key)
                seen_students[key] = student
                if password:
                    issued["students"].append(
                        ("Ученик", row["fio"], student.login, password, row["group"], row["faculty"])
                    )
            Enrollment.objects.get_or_create(group=groups[row["group"]], student=student)

        deactivated = self._deactivate_demo_russian(language, set(groups.values()))
        out = self._write_credentials(issued)

        self.stdout.write(
            self.style.SUCCESS(
                f"Русский: {len(teachers)} преподавателя, {len(assistants)} ассистента, "
                f"{len(groups)} групп, {len(seen_students)} учеников."
            )
        )
        if deactivated:
            self.stdout.write(f"Отключены демо-записи: {deactivated}")
        self.stdout.write(f"Логины и пароли: {out}")

    def _default_file(self) -> Path:
        downloads = Path.home() / "Downloads"
        matches = [p for p in downloads.glob("*.xlsx") if "Umumiy" in p.name and "Русский" in p.name]
        if matches:
            return matches[0]
        fallback = Path(settings.BASE_DIR) / "data" / "umumiy_ru.xlsx"
        return fallback

    def _upsert_staff(self, *, first_name: str, role: str, lead_teacher=None):
        user = User.objects.filter(role=role, first_name=first_name, last_name="").first()
        created = user is None
        password = ""
        if created:
            user = User(
                login=generate_login(first_name, "", role),
                first_name=first_name,
                role=role,
            )
            password = generate_password()
            user.set_password(password)
        user.role = role
        user.first_name = first_name
        user.lead_teacher = lead_teacher
        user.is_active = True
        user.profile_completed = True
        user.must_change_password = False
        user.save()
        return user, password

    def _upsert_group(self, code: str, language, teacher) -> Group:
        name = f"Русский · {code}"
        group = Group.objects.filter(name=name).first()
        if group is None:
            group = Group(name=name, language=language)
        group.language = language
        group.teacher = teacher
        group.level = Group.Level.A1
        group.schedule = SCHEDULES.get(code, "")
        group.is_active = True
        group.save()
        return group

    def _upsert_student(self, row: dict, key: str):
        user = User.objects.filter(notes=key).first()
        created = user is None
        password = ""
        if created:
            user = User(
                login=generate_login(row["last_name"], row["first_name"], User.Role.STUDENT),
                role=User.Role.STUDENT,
            )
            password = generate_password()
            user.set_password(password)
        user.last_name = row["last_name"]
        user.first_name = row["first_name"]
        user.middle_name = row["middle_name"]
        user.faculty = row["faculty"]
        user.phone = row["phone"]
        user.notes = key
        user.role = User.Role.STUDENT
        user.is_active = True
        user.profile_completed = True
        user.must_change_password = False
        user.save()
        return user, password

    def _deactivate_demo_russian(self, language, keep_groups) -> int:
        keep_ids = {group.pk for group in keep_groups}
        count = 0
        for login in DEMO_TEACHER_LOGINS + DEMO_ASSISTANT_LOGINS:
            user = User.objects.filter(login=login).first()
            if user and user.is_active:
                user.is_active = False
                user.save(update_fields=["is_active"])
                count += 1
        dummy_students = User.objects.filter(login__regex=r"^s\.ru\d+$", is_active=True)
        count += dummy_students.update(is_active=False)
        dummy_groups = Group.objects.filter(language=language, is_active=True).exclude(pk__in=keep_ids)
        dummy_groups = dummy_groups.filter(name__contains="группа") | dummy_groups.filter(
            name="B1 Русский как иностранный"
        )
        count += dummy_groups.update(is_active=False)
        return count

    def _write_credentials(self, issued: dict) -> Path:
        out_dir = Path(settings.BASE_DIR) / "var"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / "ru_credentials.xlsx"
        wb = Workbook()
        wb.remove(wb.active)
        _write_sheet(wb, "Преподаватели", issued["teachers"])
        _write_sheet(wb, "Ассистенты", issued["assistants"])
        _write_sheet(wb, "Ученики", issued["students"])
        wb.save(path)
        return path
