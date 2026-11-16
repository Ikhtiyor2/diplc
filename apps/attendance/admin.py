from django.contrib import admin

from .models import (
    Attendance,
    AttendanceSession,
    LectureAttendance,
    LectureCheckInSession,
    LectureSession,
    LectureStream,
)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("student", "group", "lesson_date", "kind", "status")
    list_filter = ("group", "status", "kind", "lesson_date")
    search_fields = ("student__last_name", "student__first_name")


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("group", "lesson_date", "token", "is_open", "created_at")
    list_filter = ("is_open", "group")


@admin.register(LectureStream)
class LectureStreamAdmin(admin.ModelAdmin):
    list_display = ("name", "lector", "schedule", "room", "is_active")
    list_filter = ("is_active",)
    filter_horizontal = ("groups",)


@admin.register(LectureCheckInSession)
class LectureCheckInSessionAdmin(admin.ModelAdmin):
    list_display = ("stream", "lesson_date", "token", "is_open", "created_at")
    list_filter = ("is_open", "stream")


@admin.register(LectureSession)
class LectureSessionAdmin(admin.ModelAdmin):
    list_display = ("stream", "date", "topic", "is_cancelled")
    list_filter = ("is_cancelled", "stream")


@admin.register(LectureAttendance)
class LectureAttendanceAdmin(admin.ModelAdmin):
    list_display = ("session", "student", "status")
    list_filter = ("status", "session__stream")
