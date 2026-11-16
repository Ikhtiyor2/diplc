from django.conf import settings
from django.db import models


class Test(models.Model):
    class Kind(models.TextChoices):
        READING = "reading", "Чтение"
        LISTENING = "listening", "Аудирование"
        GENERAL = "general", "Общий тест"

    title = models.CharField("Название", max_length=200)
    description = models.TextField("Описание", blank=True)
    kind = models.CharField("Формат", max_length=16, choices=Kind.choices, default=Kind.GENERAL)
    instructions = models.TextField("Инструкция для ученика", blank=True)
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="tests")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tests",
    )
    time_limit_minutes = models.PositiveIntegerField("Лимит времени, мин", null=True, blank=True)
    is_published = models.BooleanField("Опубликован", default=True)
    available_until = models.DateTimeField("Доступен до", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Тест"
        verbose_name_plural = "Тесты"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_ielts(self) -> bool:
        return self.kind in {self.Kind.READING, self.Kind.LISTENING}

    @property
    def exam_profile(self) -> dict:
        from apps.assessments.exams import profile_for

        code = getattr(getattr(self.group, "language", None), "code", "en")
        return profile_for(code)

    @property
    def format_label(self) -> str:
        profile = self.exam_profile
        if self.kind == self.Kind.READING:
            return f"{profile['exam']} · {profile['reading_name']}"
        if self.kind == self.Kind.LISTENING:
            return f"{profile['exam']} · {profile['listening_name']}"
        return "Общий тест"


class TestSection(models.Model):
    class Kind(models.TextChoices):
        PASSAGE = "passage", "Текст / Passage"
        AUDIO = "audio", "Аудио / Section"

    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField("Название секции", max_length=160)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.PASSAGE)
    body = models.TextField("Текст пассажа или транскрипт", blank=True)
    audio = models.FileField("Аудио", upload_to="tests/audio/", blank=True)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Секция теста"
        verbose_name_plural = "Секции теста"

    def __str__(self) -> str:
        return f"{self.test.title}: {self.title}"


class Question(models.Model):
    class Type(models.TextChoices):
        SINGLE = "single", "Multiple choice (один ответ)"
        MULTIPLE = "multiple", "Multiple choice (несколько)"
        TFNG = "tfng", "True / False / Not Given"
        YNNG = "ynng", "Yes / No / Not Given"
        FILL_BLANK = "fill_blank", "Sentence / note completion"
        SHORT = "short", "Short-answer"
        MATCH = "match", "Matching"
        HEADING = "heading", "Matching headings"
        TEXT = "text", "Развёрнутый ответ"

    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="questions")
    section = models.ForeignKey(
        TestSection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="questions",
    )
    type = models.CharField("Тип", max_length=20, choices=Type.choices)
    question_text = models.TextField("Вопрос / инструкция")
    payload = models.JSONField("Данные вопроса", default=dict, blank=True)
    points = models.PositiveIntegerField("Баллы", default=1)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Вопрос"
        verbose_name_plural = "Вопросы"

    def __str__(self) -> str:
        return self.question_text[:80]

    @property
    def gaps(self):
        return (self.payload or {}).get("items") or []

    @property
    def is_notes(self) -> bool:
        payload = self.payload or {}
        return self.type == self.Type.FILL_BLANK and bool(payload.get("body"))

    @property
    def span(self) -> int:
        payload = self.payload or {}
        if payload.get("body"):
            from apps.assessments.notes import blank_count

            count = max(blank_count(payload.get("body") or ""), len(payload.get("items") or []))
            return count or 1
        items = payload.get("items") or []
        if items and self.type in {
            self.Type.FILL_BLANK,
            self.Type.SHORT,
            self.Type.TFNG,
            self.Type.YNNG,
            self.Type.SINGLE,
            self.Type.MULTIPLE,
        }:
            return len(items)
        if self.type in {self.Type.MATCH, self.Type.HEADING}:
            left = payload.get("left") or []
            return len(left) or 1
        return 1


class TestAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "В процессе"
        SUBMITTED = "submitted", "Отправлен"
        GRADED = "graded", "Проверен"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="test_attempts")
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="attempts")
    answers = models.JSONField(default=dict, blank=True)
    score = models.FloatField(null=True, blank=True)
    max_score = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Результат теста"
        verbose_name_plural = "Результаты тестов"
        unique_together = ("student", "test")
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.test} — {self.student}"


class TestResult(TestAttempt):
    class Meta:
        proxy = True
        verbose_name = "Результат теста"
        verbose_name_plural = "Результаты тестов"
