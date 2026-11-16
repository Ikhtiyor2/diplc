from __future__ import annotations

from datetime import date

from django.db.models import Avg, Count, Q
from django.utils import timezone


def _lecture_slots_for_group(group, *, up_to: date | None = None) -> int:
    from apps.attendance.models import LectureSession

    if up_to is None:
        up_to = timezone.localdate()
    return (
        LectureSession.objects.filter(stream__groups=group, is_cancelled=False, date__lte=up_to)
        .distinct()
        .count()
    )


def _lecture_present_for_student(student, group, *, up_to: date | None = None) -> int:
    from apps.attendance.models import LectureAttendance, LectureSession

    if up_to is None:
        up_to = timezone.localdate()
    session_ids = LectureSession.objects.filter(
        stream__groups=group, is_cancelled=False, date__lte=up_to
    ).values_list("pk", flat=True)
    return LectureAttendance.objects.filter(
        student=student, session_id__in=session_ids, status=LectureAttendance.Status.PRESENT
    ).count()


def attendance_percent(student, group=None) -> float | None:
    from apps.attendance.models import Attendance

    qs = Attendance.objects.filter(student=student, kind=Attendance.Kind.CLASS)
    if group is not None:
        qs = qs.filter(group=group)
    class_total = qs.count()
    class_present = qs.filter(status=Attendance.Status.PRESENT).count()

    lecture_total = 0
    lecture_present = 0
    if group is not None:
        lecture_total = _lecture_slots_for_group(group)
        lecture_present = _lecture_present_for_student(student, group)
    else:
        from apps.groups.models import Enrollment

        for enrollment in Enrollment.objects.filter(student=student).select_related("group"):
            lecture_total += _lecture_slots_for_group(enrollment.group)
            lecture_present += _lecture_present_for_student(student, enrollment.group)

    total = class_total + lecture_total
    if not total:
        return None
    present = class_present + lecture_present
    return round(present * 100 / total, 1)


def average_score(student, group=None) -> float | None:
    from apps.homework.models import Submission
    from apps.assessments.models import TestAttempt

    homework_qs = Submission.objects.filter(student=student, score__isnull=False)
    test_qs = TestAttempt.objects.filter(student=student, score__isnull=False).exclude(status=TestAttempt.Status.IN_PROGRESS)
    if group is not None:
        homework_qs = homework_qs.filter(assignment__group=group)
        test_qs = test_qs.filter(test__group=group)

    values = list(homework_qs.values_list("score", flat=True)) + list(test_qs.values_list("score", flat=True))
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def assignment_progress(student, group=None) -> dict:
    from apps.homework.models import Assignment, Submission

    assignments = Assignment.objects.filter(is_published=True)
    if group is not None:
        assignments = assignments.filter(group=group)
    else:
        assignments = assignments.filter(group__enrollments__student=student)
    total = assignments.distinct().count()
    done = Submission.objects.filter(
        student=student,
        assignment__in=assignments,
        status__in=[Submission.Status.SUBMITTED, Submission.Status.GRADED],
    ).count()
    returned = Submission.objects.filter(
        student=student,
        assignment__in=assignments,
        status=Submission.Status.RETURNED,
    ).count()
    return {"total": total, "done": done, "pending": max(total - done, 0), "returned": returned}


def student_stats(student, group=None) -> dict:
    from apps.homework.models import Submission

    progress = assignment_progress(student, group)
    homework = Submission.objects.filter(student=student, score__isnull=False)
    if group is not None:
        homework = homework.filter(assignment__group=group)
    scores = list(homework.values_list("score", flat=True))
    average = round(sum(scores) / len(scores), 1) if scores else None
    attendance = attendance_percent(student, group)
    last = homework.order_by("-graded_at", "-updated_at").first()
    reasons = []
    if average is not None and average < 60:
        reasons.append("низкий балл")
    if attendance is not None and attendance < 70:
        reasons.append("пропуски")
    if progress["pending"] >= 2:
        reasons.append("несданные ДЗ")
    if progress["returned"]:
        reasons.append("на доработке")
    return {
        "average": average,
        "attendance": attendance,
        "progress": progress,
        "graded_count": len(scores),
        "last_score": last.score if last else None,
        "risk": bool(reasons),
        "risk_reasons": reasons,
    }


def group_kpis(group) -> dict:
    students = [item.student for item in group.enrollments.select_related("student")]
    att = [attendance_percent(s, group) for s in students]
    scores = [average_score(s, group) for s in students]
    att = [v for v in att if v is not None]
    scores = [v for v in scores if v is not None]
    return {
        "students": len(students),
        "attendance": round(sum(att) / len(att), 1) if att else None,
        "average": round(sum(scores) / len(scores), 1) if scores else None,
    }


def attendance_by_month(limit: int = 6) -> list[dict]:
    from apps.attendance.models import Attendance
    from django.db.models.functions import TruncMonth

    rows = (
        Attendance.objects.filter(kind=Attendance.Kind.CLASS)
        .annotate(month=TruncMonth("lesson_date"))
        .values("month")
        .annotate(total=Count("id"), present=Count("id", filter=Q(status="present")))
        .order_by("month")
    )
    data = []
    for row in rows:
        month = row["month"]
        if not month:
            continue
        percent = round(row["present"] * 100 / row["total"], 1) if row["total"] else 0
        data.append({"label": month.strftime("%m.%Y"), "value": percent})
    return data[-limit:]


def group_performance() -> list[dict]:
    from apps.groups.models import Group

    result = []
    for group in Group.objects.select_related("language", "teacher"):
        kpis = group_kpis(group)
        result.append(
            {
                "id": group.id,
                "name": group.name,
                "language": group.language.name,
                "attendance": kpis["attendance"] or 0,
                "average": kpis["average"] or 0,
                "students": kpis["students"],
            }
        )
    return result


def today() -> date:
    return date.today()
