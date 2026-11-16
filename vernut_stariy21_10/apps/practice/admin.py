from django.contrib import admin

from .models import Exercise, ExerciseAttempt


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("title", "language", "type", "is_published", "created_by")
    list_filter = ("language", "type", "is_published")
    search_fields = ("title",)


@admin.register(ExerciseAttempt)
class ExerciseAttemptAdmin(admin.ModelAdmin):
    list_display = ("exercise", "student", "score", "completed_at")
