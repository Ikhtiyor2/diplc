from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


REVIEW_LOCK_SECONDS = 90


class Assignment(models.Model):
    title = models.CharField("Название", max_length=200)
    description = models.TextField("Инструкция", blank=True)
    deadline = models.DateTimeField("Дедлайн", null=True, blank=True)
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="assignments")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_assignments",
    )
    is_published = models.BooleanField("Опубликовано", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Домашнее задание"
        verbose_name_plural = "Домашние задания"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class AssignmentFile(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="assignments/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name or self.file.name


class AssignmentItem(models.Model):
    class Kind(models.TextChoices):
        TEXT = "text", "Текстовый вопрос"
        EXERCISE = "exercise", "Упражнение"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TEXT)
    prompt = models.TextField("Вопрос / инструкция")
    exercise = models.ForeignKey("practice.Exercise", on_delete=models.SET_NULL, null=True, blank=True)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.prompt[:60]


class Submission(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SUBMITTED = "submitted", "На проверке"
        RETURNED = "returned", "На доработке"
        GRADED = "graded", "Проверено"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    answer = models.TextField("Ответ", blank=True)
    answers = models.JSONField("Ответы по вопросам", default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    score = models.FloatField("Оценка", null=True, blank=True)
    feedback = models.TextField("Комментарий преподавателя", blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graded_submissions",
    )
    reviewing_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_reviews",
        verbose_name="Сейчас проверяет",
    )
    reviewing_at = models.DateTimeField("Начало проверки", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Сдача задания"
        verbose_name_plural = "Сдачи заданий"
        unique_together = ("assignment", "student")
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.assignment} — {self.student}"

    def lock_active(self) -> bool:
        if self.status == self.Status.GRADED:
            return False
        if not self.reviewing_by_id or not self.reviewing_at:
            return False
        age = timezone.now() - self.reviewing_at
        return age.total_seconds() < REVIEW_LOCK_SECONDS

    @property
    def review_state(self) -> str:
        if self.status == self.Status.GRADED:
            return "done"
        if self.lock_active():
            return "checking"
        return "pending"

    @property
    def answers_map(self) -> dict:
        data = self.answers
        return data if isinstance(data, dict) else {}

    def claim_review(self, user) -> bool:
        with transaction.atomic():
            # Postgres rejects FOR UPDATE with OUTER JOIN from nullable select_related().
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.status == locked.Status.GRADED:
                self.status = locked.status
                return False
            if locked.lock_active() and locked.reviewing_by_id != user.pk:
                self.reviewing_by = locked.reviewing_by
                self.reviewing_at = locked.reviewing_at
                return False
            locked.reviewing_by = user
            locked.reviewing_at = timezone.now()
            locked.save(update_fields=["reviewing_by", "reviewing_at"])
            self.reviewing_by = user
            self.reviewing_at = locked.reviewing_at
            return True

    def touch_review(self, user) -> bool:
        if self.reviewing_by_id != user.pk:
            return False
        self.reviewing_at = timezone.now()
        self.save(update_fields=["reviewing_at"])
        return True

    def release_review(self, user=None) -> None:
        if user and self.reviewing_by_id and self.reviewing_by_id != user.pk:
            return
        self.reviewing_by = None
        self.reviewing_at = None
        self.save(update_fields=["reviewing_by", "reviewing_at"])


class SubmissionFile(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="submissions/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name or self.file.name

    def public_url(self) -> str | None:
        if not self.file:
            return None
        try:
            return self.file.url
        except Exception:
            return None
