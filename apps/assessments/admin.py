from django.contrib import admin

from .models import Question, Test, TestAttempt, TestSection


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0


class TestSectionInline(admin.StackedInline):
    model = TestSection
    extra = 0


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "group", "is_published", "created_by")
    list_filter = ("kind", "group", "is_published")
    inlines = [TestSectionInline, QuestionInline]


@admin.register(TestAttempt)
class TestAttemptAdmin(admin.ModelAdmin):
    list_display = ("test", "student", "score", "status", "submitted_at")
    list_filter = ("status", "test__group")
