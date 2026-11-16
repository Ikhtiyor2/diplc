from __future__ import annotations

from datetime import date

from apps.groups.models import Enrollment


def resolve_lecture_session(stream, lesson_date: date, *, topic: str = "", create: bool = False):
    from apps.attendance.models import LectureSession

    qs = LectureSession.objects.filter(stream=stream, date=lesson_date, is_cancelled=False)
    session = qs.first()
    if session or not create:
        return session
    return LectureSession.objects.create(
        stream=stream,
        date=lesson_date,
        topic=(topic or "").strip() or "Лекция",
    )


def stream_student_rows(stream) -> list[dict]:
    group_ids = list(stream.groups.filter(is_active=True).values_list("pk", flat=True))
    if not group_ids:
        return []
    enrollments = (
        Enrollment.objects.filter(group_id__in=group_ids, student__is_active=True)
        .select_related("student", "group")
        .order_by("student__last_name", "student__first_name")
    )
    by_student: dict[int, dict] = {}
    for enrollment in enrollments:
        student = enrollment.student
        bucket = by_student.get(student.pk)
        if not bucket:
            bucket = {"student": student, "groups": []}
            by_student[student.pk] = bucket
        bucket["groups"].append(enrollment.group)
    rows = list(by_student.values())
    rows.sort(key=lambda row: (row["student"].last_name, row["student"].first_name))
    return rows


def student_in_stream(student, stream) -> bool:
    group_ids = stream.groups.filter(is_active=True).values_list("pk", flat=True)
    if not group_ids:
        return False
    return Enrollment.objects.filter(student=student, group_id__in=group_ids).exists()


def lecture_present_student_ids(stream, lesson_date) -> set[int]:
    from apps.attendance.models import LectureAttendance

    session = resolve_lecture_session(stream, lesson_date, create=False)
    if not session:
        return set()
    return set(
        LectureAttendance.objects.filter(
            session=session,
            status=LectureAttendance.Status.PRESENT,
        ).values_list("student_id", flat=True)
    )


def refresh_stream_enrollments(stream) -> None:
    from apps.attendance.signals import refresh_enrollment

    group_ids = stream.groups.values_list("pk", flat=True)
    pairs = Enrollment.objects.filter(group_id__in=group_ids).values_list("student_id", "group_id").distinct()
    for student_id, group_id in pairs:
        refresh_enrollment(student_id, group_id)
