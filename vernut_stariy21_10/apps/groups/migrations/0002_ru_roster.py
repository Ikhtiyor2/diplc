import json
import sys
from pathlib import Path

from django.db import migrations
from django.utils import timezone


def _running_tests() -> bool:
    return "test" in sys.argv


def _load_roster() -> dict:
    path = Path(__file__).resolve().parent.parent / "data" / "ru_roster.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _upsert_user(User, *, login: str, role: str, password: str, **fields):
    user = User.objects.filter(login__iexact=login).first()
    if user is None:
        user = User(login=login, created_at=timezone.now())
    user.login = login
    user.role = role
    user.password = password
    user.is_active = True
    user.profile_completed = True
    user.must_change_password = False
    user.is_staff = False
    user.is_superuser = False
    for key, value in fields.items():
        setattr(user, key, value)
    user.save()
    return user


def seed_ru_roster(apps, schema_editor):
    if _running_tests():
        return

    User = apps.get_model("accounts", "User")
    Language = apps.get_model("groups", "Language")
    Group = apps.get_model("groups", "Group")
    Enrollment = apps.get_model("groups", "Enrollment")
    data = _load_roster()

    language, _ = Language.objects.get_or_create(
        code="ru",
        defaults={"name": "Русский", "native_name": "Русский", "flag": "🇷🇺"},
    )

    teachers = {}
    for item in data["teachers"]:
        teachers[item["login"]] = _upsert_user(
            User,
            login=item["login"],
            role="teacher",
            password=item["password"],
            first_name=item.get("first_name") or "",
            last_name=item.get("last_name") or "",
        )

    for item in data["assistants"]:
        lead = teachers.get(item.get("lead_teacher") or "")
        _upsert_user(
            User,
            login=item["login"],
            role="assistant",
            password=item["password"],
            first_name=item.get("first_name") or "",
            last_name=item.get("last_name") or "",
            lead_teacher=lead,
        )

    groups = {}
    for item in data["groups"]:
        group = Group.objects.filter(name=item["name"]).first()
        if group is None:
            group = Group(name=item["name"], language=language)
        group.language = language
        group.teacher = teachers.get(item.get("teacher") or "")
        group.level = item.get("level") or "A1"
        group.schedule = item.get("schedule") or ""
        group.room = item.get("room") or ""
        group.is_active = True
        group.save()
        groups[item["name"]] = group

    for item in data["students"]:
        student = _upsert_user(
            User,
            login=item["login"],
            role="student",
            password=item["password"],
            first_name=item.get("first_name") or "",
            last_name=item.get("last_name") or "",
            middle_name=item.get("middle_name") or "",
            faculty=item.get("faculty") or "",
            phone=item.get("phone") or "",
            notes=item.get("notes") or "",
        )
        for group_name in item.get("groups") or []:
            group = groups.get(group_name)
            if group is not None:
                Enrollment.objects.get_or_create(student=student, group=group)


def unseed_ru_roster(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Group = apps.get_model("groups", "Group")
    data = _load_roster()
    logins = [item["login"] for item in data["teachers"] + data["assistants"] + data["students"]]
    User.objects.filter(login__in=logins).delete()
    Group.objects.filter(name__in=[item["name"] for item in data["groups"]]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_platform_admins"),
        ("groups", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_ru_roster, unseed_ru_roster),
    ]
