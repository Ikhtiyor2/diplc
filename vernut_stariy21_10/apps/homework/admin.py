from django.contrib import admin

from .models import Assignment, AssignmentFile, AssignmentItem, Submission, SubmissionFile


class AssignmentFileInline(admin.TabularInline):
    model = AssignmentFile
    extra = 0


class AssignmentItemInline(admin.TabularInline):
    model = AssignmentItem
    extra = 0


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "deadline", "is_published", "created_by")
    list_filter = ("group", "is_published")
    search_fields = ("title",)
    inlines = [AssignmentItemInline, AssignmentFileInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "student", "status", "score", "submitted_at")
    list_filter = ("status", "assignment__group")


admin.site.register(SubmissionFile)
