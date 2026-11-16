from django.conf import settings
from django.db import models


class Exercise(models.Model):
    class Type(models.TextChoices):
        VOCABULARY = "vocabulary", "Vocabulary"
        MATCHING = "matching", "Matching"
        SENTENCE = "sentence_builder", "Sentence Builder"
        GRAMMAR = "grammar", "Grammar Test"
        READING = "reading", "Reading"
        LISTENING = "listening", "Listening"
        WRITING = "writing", "Writing"

    title = models.CharField("Название", max_length=200)
    language = models.ForeignKey("groups.Language", on_delete=models.PROTECT, related_name="exercises")
    type = models.CharField("Тип", max_length=32, choices=Type.choices)
    prompt = models.TextField("Задание")
    content = models.JSONField("Содержимое", default=dict, blank=True)
    audio = models.FileField("Аудио", upload_to="exercises/audio/", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_exercises",
    )
    is_published = models.BooleanField("Опубликовано", default=True)
    level = models.CharField("Уровень", max_length=4, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Упражнение"
        verbose_name_plural = "Упражнения"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class ExerciseAttempt(models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exercise_attempts")
    answers = models.JSONField(default=dict, blank=True)
    score = models.FloatField(null=True, blank=True)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Попытка упражнения"
        verbose_name_plural = "Попытки упражнений"
        ordering = ["-completed_at"]

    def __str__(self) -> str:
        return f"{self.exercise} — {self.student}"
