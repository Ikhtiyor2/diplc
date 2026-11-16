from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Присутствовал"
        ABSENT = "absent", "Отсутствовал"

    class Kind(models.TextChoices):
        CLASS = "class", "Занятие в группе"
        LECTURE = "lecture", "Лекция (устар.)"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name="Ученик",
    )
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="attendance_records")
    lesson_date = models.DateField("Дата занятия")
    kind = models.CharField(
        "Тип занятия",
        max_length=16,
        choices=Kind.choices,
        default=Kind.CLASS,
    )
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
        unique_together = ("student", "group", "lesson_date", "kind")
        ordering = ["-lesson_date", "student__last_name"]

    def __str__(self) -> str:
        return f"{self.student} {self.lesson_date} {self.status}"


class LectureStream(models.Model):
    name = models.CharField("Название потока", max_length=160)
    lector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lecture_streams",
        verbose_name="Лектор",
        limit_choices_to={"role__in": ["teacher", "lector"]},
    )
    groups = models.ManyToManyField("groups.Group", related_name="lecture_streams", verbose_name="Группы")
    schedule = models.CharField("Расписание", max_length=160, blank=True)
    room = models.CharField("Аудитория", max_length=32, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Поток лекций"
        verbose_name_plural = "Потоки лекций"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LectureSession(models.Model):
    stream = models.ForeignKey(
        LectureStream,
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name="Поток",
    )
    date = models.DateField("Дата")
    topic = models.CharField("Тема", max_length=240)
    is_cancelled = models.BooleanField("Отменена", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Лекция"
        verbose_name_plural = "Лекции"
        ordering = ["-date", "stream__name"]
        unique_together = ("stream", "date")

    def __str__(self) -> str:
        return f"{self.stream.name} · {self.date}"


class LectureAttendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Присутствовал"
        ABSENT = "absent", "Отсутствовал"

    session = models.ForeignKey(
        LectureSession,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        verbose_name="Лекция",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lecture_attendance_records",
        verbose_name="Ученик",
        limit_choices_to={"role": "student"},
    )
    status = models.CharField("Статус", max_length=16, choices=Status.choices)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marked_lecture_attendance",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Посещаемость лекции"
        verbose_name_plural = "Посещаемость лекций"
        unique_together = ("session", "student")
        ordering = ["-session__date", "student__last_name"]

    def __str__(self) -> str:
        return f"{self.student} {self.session} {self.status}"


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
        while cls.objects.filter(token=token).exists() or LectureCheckInSession.objects.filter(token=token).exists():
            token = make_checkin_token()
        return cls.objects.create(group=group, lesson_date=lesson_date, token=token, created_by=user)


class LectureCheckInSession(models.Model):
    stream = models.ForeignKey(
        LectureStream,
        on_delete=models.CASCADE,
        related_name="checkin_sessions",
        verbose_name="Поток",
    )
    lesson_date = models.DateField("Дата лекции")
    token = models.CharField("Код", max_length=16, unique=True)
    is_open = models.BooleanField("Сбор открыт", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_lecture_checkins",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Сбор посещаемости лекции"
        verbose_name_plural = "Сборы посещаемости лекций"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.stream} {self.lesson_date} {self.token}"

    @classmethod
    def start(cls, stream, user, lesson_date):
        open_session = cls.objects.filter(stream=stream, lesson_date=lesson_date, is_open=True).first()
        if open_session:
            return open_session
        token = make_checkin_token()
        while cls.objects.filter(token=token).exists() or AttendanceSession.objects.filter(token=token).exists():
            token = make_checkin_token()
        return cls.objects.create(stream=stream, lesson_date=lesson_date, token=token, created_by=user)
