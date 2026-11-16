from django.contrib import admin

from .models import Enrollment, Group, Language


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "native_name")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "language", "teacher", "level", "is_active")
    list_filter = ("language", "level", "is_active")
    search_fields = ("name",)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "group", "attendance_percent", "joined_at")
    list_filter = ("group",)
