from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


HEADER_FILL = PatternFill("solid", fgColor="0F6E63")
HEADER_FONT = Font(color="FFFFFF", bold=True)
PRESENT_FILL = PatternFill("solid", fgColor="D9F2E4")
ABSENT_FILL = PatternFill("solid", fgColor="F8D7D4")
TITLE_FONT = Font(bold=True, size=14)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center")
GRID = Border(
    left=Side(style="thin", color="E4E0D8"),
    right=Side(style="thin", color="E4E0D8"),
    top=Side(style="thin", color="E4E0D8"),
    bottom=Side(style="thin", color="E4E0D8"),
)


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


def _sheet_title(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch not in "[]:*?/\\")
    return (cleaned or "Sheet")[:31]


def _download_name(group) -> str:
    raw = f"Посещаемость {group.name}.xlsx"
    return "".join(ch if ch not in '\\/:*?"<>|' else " " for ch in raw).strip()


def _enrolled_students(group):
    from apps.accounts.models import User

    return list(
        User.objects.filter(enrollments__group=group, role=User.Role.STUDENT, is_active=True)
        .distinct()
        .order_by("last_name", "first_name", "login")
    )


def _mark(status: str | None):
    if status == "present":
        return "+", PRESENT_FILL
    if status == "absent":
        return "-", ABSENT_FILL
    return None, None


def _write_journal_sheet(sheet, group, *, title: str, columns: list, marks: dict, cabinet_percent: bool):
    from apps.web.i18n import translate as _

    students = _enrolled_students(group)
    sheet.title = _sheet_title(title)
    sheet["A1"] = _("Группа")
    sheet["A1"].font = TITLE_FONT
    sheet["B1"] = group.name
    sheet["B1"].font = TITLE_FONT
    sheet["A2"] = _("+: был, -: не был")
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4)

    headers = [_("№"), _("Фамилия"), _("Имя"), _("Логин")]
    headers.extend(columns)
    headers.extend([_("Был"), _("Не был"), _("%")])
    if cabinet_percent:
        headers.append(_("В кабинете %"))
    header_row = 3
    for col, header in enumerate(headers, start=1):
        cell = sheet.cell(header_row, col, header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = GRID
        if hasattr(header, "year"):
            cell.number_format = "DD.MM.YYYY"

    from apps.core.metrics import attendance_percent

    for index, student in enumerate(students, start=1):
        row = header_row + index
        present = absent = 0
        values = [index, student.last_name, student.first_name, student.login]
        for column in columns:
            status = marks.get((student.pk, column))
            symbol, fill = _mark(status)
            if status == "present":
                present += 1
            elif status == "absent":
                absent += 1
            values.append(symbol)
        marked = present + absent
        values.append(present)
        values.append(absent)
        values.append(round(present * 100 / marked, 1) if marked else None)
        if cabinet_percent:
            values.append(attendance_percent(student, group))
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row, col, value)
            cell.border = GRID
            cell.alignment = CENTER if col == 1 or col > 4 else LEFT
            if col > 4 and col <= 4 + len(columns):
                _symbol, fill = _mark("present" if value == "+" else "absent" if value == "-" else None)
                if fill is not None:
                    cell.fill = fill
                    cell.alignment = CENTER
            if col > 4 + len(columns) + 2 and isinstance(value, float):
                cell.number_format = "0.0"
                cell.alignment = CENTER

    last_col = get_column_letter(len(headers))
    last_row = max(header_row, header_row + len(students))
    sheet.freeze_panes = "E4"
    sheet.auto_filter.ref = f"A{header_row}:{last_col}{last_row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = "1:3"
    sheet.page_setup.horizontalCentered = True
    sheet.row_dimensions[header_row].height = 32
    widths = {1: 6, 2: max(18, min(len(group.name) + 2, 32)), 3: 16, 4: 16}
    for col in range(1, len(headers) + 1):
        letter = get_column_letter(col)
        sheet.column_dimensions[letter].width = widths.get(col, 12)
    if len(headers) > 4 + len(columns):
        for col in range(5 + len(columns), len(headers) + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 14


def export_attendance(group) -> HttpResponse:
    from apps.attendance.models import Attendance, LectureAttendance, LectureSession
    from apps.web.i18n import translate as _

    students = _enrolled_students(group)
    student_ids = [student.pk for student in students]
    class_dates = list(
        Attendance.objects.filter(group=group, kind=Attendance.Kind.CLASS, student_id__in=student_ids)
        .values_list("lesson_date", flat=True)
        .distinct()
        .order_by("lesson_date")
    )
    class_marks = {
        (rec.student_id, rec.lesson_date): rec.status
        for rec in Attendance.objects.filter(group=group, kind=Attendance.Kind.CLASS, student_id__in=student_ids)
    }
    book = Workbook()
    _write_journal_sheet(
        book.active,
        group,
        title=_("Занятия"),
        columns=class_dates,
        marks=class_marks,
        cabinet_percent=True,
    )

    session_ids = list(
        LectureSession.objects.filter(stream__groups=group, is_cancelled=False).values_list("pk", flat=True).distinct()
    )
    sessions = list(LectureSession.objects.filter(pk__in=session_ids).select_related("stream").order_by("date", "id"))
    if sessions:
        seen_dates = {}
        columns = []
        key_by_session = {}
        used = set()
        for session in sessions:
            seen_dates[session.date] = seen_dates.get(session.date, 0) + 1
        for session in sessions:
            if seen_dates[session.date] > 1:
                key = f"{session.date.strftime('%d.%m.%Y')} {session.stream.name}"
            else:
                key = session.date
            if key in used:
                key = f"{session.date.strftime('%d.%m.%Y')} {session.stream.name} {session.pk}"
            used.add(key)
            columns.append(key)
            key_by_session[session.pk] = key
        lecture_marks = {}
        records = LectureAttendance.objects.filter(session_id__in=session_ids, student_id__in=student_ids)
        for rec in records:
            lecture_marks[(rec.student_id, key_by_session[rec.session_id])] = rec.status
        _write_journal_sheet(
            book.create_sheet(),
            group,
            title=_("Лекции"),
            columns=columns,
            marks=lecture_marks,
            cabinet_percent=False,
        )

    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    download_name = _download_name(group)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f"attachment; filename=\"attendance_{group.id}.xlsx\"; filename*=UTF-8''{quote(download_name)}"
    )
    return response


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
