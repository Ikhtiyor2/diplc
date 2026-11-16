from __future__ import annotations

from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


HEADER_FILL = PatternFill("solid", fgColor="0F6E63")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def workbook_response(name: str, headers: list[str], rows: list[list]) -> HttpResponse:
    book = Workbook()
    sheet = book.active
    sheet.title = name[:31]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        sheet.append(row)
    for column in sheet.columns:
        max_length = 12
        column_letter = column[0].column_letter
        for cell in column:
            max_length = max(max_length, len(str(cell.value or "")))
        sheet.column_dimensions[column_letter].width = min(max_length + 2, 40)
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
    return response


def export_attendance(group) -> HttpResponse:
    from apps.attendance.models import Attendance

    records = Attendance.objects.filter(group=group).select_related("student").order_by("lesson_date", "student__last_name")
    rows = [
        [
            rec.lesson_date.isoformat(),
            rec.student.last_name,
            rec.student.first_name,
            rec.student.login,
            rec.get_status_display(),
            rec.comment,
        ]
        for rec in records
    ]
    return workbook_response(
        f"attendance_{group.id}",
        ["Дата", "Фамилия", "Имя", "Логин", "Статус", "Комментарий"],
        rows,
    )


def export_grades(group) -> HttpResponse:
    from apps.accounts.models import User
    from apps.core.metrics import assignment_progress, attendance_percent, average_score
    from apps.homework.models import Submission
    from apps.assessments.models import TestAttempt

    students = User.objects.filter(enrollments__group=group, role=User.Role.STUDENT).distinct()
    rows = []
    for student in students:
        progress = assignment_progress(student, group)
        last_hw = (
            Submission.objects.filter(student=student, assignment__group=group, score__isnull=False)
            .order_by("-graded_at")
            .first()
        )
        last_test = (
            TestAttempt.objects.filter(student=student, test__group=group, score__isnull=False)
            .order_by("-submitted_at")
            .first()
        )
        rows.append(
            [
                student.last_name,
                student.first_name,
                student.login,
                attendance_percent(student, group) or "—",
                average_score(student, group) or "—",
                progress["done"],
                progress["pending"],
                last_hw.score if last_hw else "—",
                last_test.score if last_test else "—",
            ]
        )
    return workbook_response(
        f"grades_{group.id}",
        [
            "Фамилия",
            "Имя",
            "Логин",
            "Посещаемость %",
            "Средний балл",
            "Сдано ДЗ",
            "Не сдано ДЗ",
            "Последняя оценка ДЗ",
            "Последний тест",
        ],
        rows,
    )
