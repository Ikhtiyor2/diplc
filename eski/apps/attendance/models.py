from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Присутствовал"
        ABSENT = "absent", "Отсутствовал"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name="Ученик",
    )
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="attendance_records")
    lesson_date = models.DateField("Дата занятия")
    status = models.CharField("Статус", max_length=16, choices=Status.choices)
    comment = models.CharField("Комментарий", max_length=200, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marked_attendance",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Посещаемость"
        verbose_name_plural = "Посещаемость"
        unique_together = ("student", "group", "lesson_date")
        ordering = ["-lesson_date", "student__last_name"]

    def __str__(self) -> str:
        return f"{self.student} {self.lesson_date} {self.status}"


def make_checkin_token() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return get_random_string(8, alphabet)


class AttendanceSession(models.Model):
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="attendance_sessions")
    lesson_date = models.DateField("Дата занятия")
    token = models.CharField("Код", max_length=16, unique=True)
    is_open = models.BooleanField("Сбор открыт", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_attendance_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Сбор посещаемости"
        verbose_name_plural = "Сборы посещаемости"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.group} {self.lesson_date} {self.token}"

    @classmethod
    def start(cls, group, user, lesson_date):
        open_session = cls.objects.filter(group=group, lesson_date=lesson_date, is_open=True).first()
        if open_session:
            return open_session
        token = make_checkin_token()
        while cls.objects.filter(token=token).exists():
            token = make_checkin_token()
        return cls.objects.create(group=group, lesson_date=lesson_date, token=token, created_by=user)
