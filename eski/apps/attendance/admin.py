from django.contrib import admin

from .models import Attendance, AttendanceSession


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("student", "group", "lesson_date", "status")
    list_filter = ("group", "status", "lesson_date")
    search_fields = ("student__last_name", "student__first_name")


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("group", "lesson_date", "token", "is_open", "created_at")
    list_filter = ("is_open", "group")
