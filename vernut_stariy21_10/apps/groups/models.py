from django.db import models


class Language(models.Model):
    code = models.CharField("Код", max_length=8, unique=True)
    name = models.CharField("Название", max_length=64)
    native_name = models.CharField("На языке оригинала", max_length=64, blank=True)
    flag = models.CharField("Флаг", max_length=8, blank=True)

    class Meta:
        verbose_name = "Язык"
        verbose_name_plural = "Языки"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Group(models.Model):
    class Level(models.TextChoices):
        A1 = "A1", "A1"
        A2 = "A2", "A2"
        B1 = "B1", "B1"
        B2 = "B2", "B2"
        C1 = "C1", "C1"
        C2 = "C2", "C2"

    name = models.CharField("Название", max_length=120)
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="groups", verbose_name="Язык")
    teacher = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teaching_groups",
        verbose_name="Преподаватель",
        limit_choices_to={"role": "teacher"},
    )
    level = models.CharField("Уровень", max_length=4, choices=Level.choices, default=Level.A1)
    schedule = models.CharField("Расписание", max_length=160, blank=True)
    room = models.CharField("Аудитория", max_length=32, blank=True)
    is_active = models.BooleanField("Активна", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Группа"
        verbose_name_plural = "Группы"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Enrollment(models.Model):
    student = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="enrollments",
        limit_choices_to={"role": "student"},
    )
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="enrollments")
    joined_at = models.DateTimeField(auto_now_add=True)
    attendance_percent = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "Зачисление"
        verbose_name_plural = "Зачисления"
        unique_together = ("student", "group")
        db_table = "student_groups"

    def __str__(self) -> str:
        return f"{self.student} → {self.group}"
