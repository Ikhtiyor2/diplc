from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib import messages as django_messages
from django.contrib.auth import login as auth_login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView as DjangoLogoutView
from django.core.files.base import ContentFile
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods, require_POST
from django.conf import settings as django_settings
from urllib.parse import urlparse
from django.utils import translation

from apps.accounts.models import User
from apps.assessments.models import Question, Test, TestAttempt
from apps.assessments.notes import render_notes_html
from apps.attendance.models import (
    Attendance,
    AttendanceSession,
    LectureAttendance,
    LectureCheckInSession,
    LectureSession,
    LectureStream,
)
from apps.attendance.services import (
    lecture_present_student_ids,
    resolve_lecture_session,
    stream_student_rows,
    student_in_stream,
)
from apps.audit.models import AuditLog
from apps.core.exports import export_attendance, export_grades
from apps.core.metrics import (
    assignment_progress,
    attendance_by_month,
    attendance_percent,
    average_score,
    group_kpis,
    group_performance,
    student_stats,
)
from apps.core.scoping import can_access_group, scoped_groups, scoped_lecture_streams, scoped_students
from apps.core.services import grade_attempt, grade_exercise
from apps.groups.models import Enrollment, Group
from apps.homework.models import Assignment, AssignmentFile, Submission, SubmissionFile
from apps.notifications.models import Notification
from apps.notifications.telegram import issue_link_code
from apps.practice.models import Exercise, ExerciseAttempt

from .forms import (
    AdminCreateForm,
    AssignmentForm,
    AssistantCreateForm,
    ExerciseForm,
    GroupForm,
    LectureSessionForm,
    LectureStreamForm,
    LectorCreateForm,
    LoginForm,
    OnboardingForm,
    PasswordResetForm,
    ProfileForm,
    StudentCreateForm,
    TeacherCreateForm,
    UserEditForm,
)
from .i18n import normalize_lang, translate as _


class _TranslatedMessages:
    def success(self, request, message, extra_tags="", fail_silently=False):
        return django_messages.success(request, _(message), extra_tags=extra_tags, fail_silently=fail_silently)

    def error(self, request, message, extra_tags="", fail_silently=False):
        return django_messages.error(request, _(message), extra_tags=extra_tags, fail_silently=fail_silently)

    def info(self, request, message, extra_tags="", fail_silently=False):
        return django_messages.info(request, _(message), extra_tags=extra_tags, fail_silently=fail_silently)

    def warning(self, request, message, extra_tags="", fail_silently=False):
        return django_messages.warning(request, _(message), extra_tags=extra_tags, fail_silently=fail_silently)


messages = _TranslatedMessages()


def _short_name(person) -> str:
    last = (person.last_name or "").strip()
    first = (person.first_name or "").strip()
    if last and first:
        return f"{last} {first[0]}."
    return person.full_name or person.login


def _class_charts(rows: list[dict]) -> dict:
    return {
        "labels": [_short_name(row["student"]) for row in rows],
        "averages": [row["average"] if row["average"] is not None else 0 for row in rows],
        "attendance": [row["attendance"] if row["attendance"] is not None else 0 for row in rows],
        "homework": {
            "done": sum(row["progress"]["done"] for row in rows),
            "pending": sum(row["progress"]["pending"] for row in rows),
            "returned": sum(row["progress"].get("returned", 0) for row in rows),
        },
    }


def _require_roles(user, *roles):
    if not user.is_authenticated:
        raise PermissionDenied
    if user.is_admin:
        return
    allowed = set(roles)
    if "teacher" in allowed:
        allowed.add("assistant")
        allowed.add("lector")
    if user.role not in allowed:
        raise PermissionDenied(_("Недостаточно прав."))


def _require_primary_admin(user):
    _require_roles(user, "admin")
    if not user.is_primary_admin:
        raise PermissionDenied(_("Только главный администратор может это сделать."))


def _redirect_retired_assessments(user):
    if user.is_teacher or user.is_assistant or user.is_lector or user.is_student:
        return redirect("web:homework")
    return None


class LoginView(DjangoLoginView):
    template_name = "auth/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        auth_login(self.request, user)
        lang = normalize_lang(getattr(user, "ui_language", None))
        translation.activate(lang)
        self.request.LANGUAGE_CODE = lang
        url = self.get_redirect_url()
        if user.needs_onboarding() and not (url and url.startswith("/a/")):
            response = redirect("web:onboarding")
        else:
            response = redirect(url or "web:home")
        response.set_cookie(
            django_settings.LANGUAGE_COOKIE_NAME,
            lang,
            max_age=django_settings.LANGUAGE_COOKIE_AGE,
        )
        return response


class LogoutView(DjangoLogoutView):
    next_page = "web:landing"


def forgot_password(request):
    if request.user.is_authenticated:
        return redirect("web:home")
    form = PasswordResetForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Пароль изменён. Войдите с новым паролем.")
        return redirect("web:login")
    return render(request, "auth/forgot_password.html", {"form": form})


def landing(request):
    if request.user.is_authenticated:
        return redirect("web:home")
    return render(request, "landing.html")


@require_POST
def set_language(request):
    lang = normalize_lang(request.POST.get("language"))
    translation.activate(lang)
    request.LANGUAGE_CODE = lang
    nxt = request.POST.get("next") or ""
    if not nxt.startswith("/") or nxt.startswith("//") or nxt.startswith("/app/language"):
        referer = request.META.get("HTTP_REFERER") or "/"
        parsed = urlparse(referer)
        nxt = parsed.path or "/"
        if parsed.query:
            nxt = f"{nxt}?{parsed.query}"
    if not nxt.startswith("/") or nxt.startswith("//") or nxt.startswith("/app/language"):
        nxt = "/"
    response = redirect(nxt)
    response.set_cookie(django_settings.LANGUAGE_COOKIE_NAME, lang, max_age=django_settings.LANGUAGE_COOKIE_AGE)
    if request.user.is_authenticated:
        if getattr(request.user, "ui_language", None) != lang:
            request.user.ui_language = lang
            request.user.save(update_fields=["ui_language"])
    return response


@login_required
def home(request):
    return redirect("web:dashboard")


@login_required
def dashboard(request):
    user = request.user
    if user.is_admin:
        performance = group_performance()
        att_vals = [row["attendance"] for row in performance if row["attendance"]]
        avg_vals = [row["average"] for row in performance if row["average"]]
        ranked = sorted(performance, key=lambda row: row["average"], reverse=True)
        context = {
            "kpis": [
                {"label": "Ученики", "value": User.objects.filter(role=User.Role.STUDENT, is_active=True).count(), "hint": "активные"},
                {"label": "Преподаватели", "value": User.objects.filter(role=User.Role.TEACHER, is_active=True).count(), "hint": "в штате"},
                {
                    "label": "Лекции",
                    "value": User.objects.filter(lecture_streams__is_active=True, is_active=True).distinct().count(),
                    "hint": "ведущие потоков",
                },
                {"label": "Группы", "value": Group.objects.filter(is_active=True).count(), "hint": "активные"},
                {"label": "Посещаемость", "value": f"{round(sum(att_vals) / len(att_vals), 1) if att_vals else 0}%", "hint": "средняя"},
                {"label": "Средний балл", "value": round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else 0, "hint": "по группам"},
            ],
            "attendance_by_month": attendance_by_month(),
            "group_performance": performance,
            "best_groups": ranked[:3],
            "risk_groups": list(reversed(ranked[-3:])) if ranked else [],
            "staff_audit": AuditLog.objects.filter(
                actor__role=User.Role.ADMIN, actor__is_primary_admin=False
            ).select_related("actor")[:12]
            if user.is_primary_admin
            else [],
        }
        return render(request, "dashboards/admin.html", context)

    if user.is_teaching_staff:
        groups = _groups_with_lecture_streams(scoped_groups(user))
        pending = Submission.objects.filter(assignment__group__in=groups, status=Submission.Status.SUBMITTED).select_related(
            "student", "assignment", "reviewing_by"
        )
        upcoming = Assignment.objects.filter(group__in=groups).order_by("-created_at")[:5]
        roster = []
        for student in scoped_students(user).prefetch_related("enrollments__group")[:40]:
            stats = student_stats(student)
            roster.append({"student": student, **stats, "groups": student.enrollments.select_related("group")})
        roster.sort(key=lambda row: (not row["risk"], -(row["average"] or -1)))
        class_avgs = [row["average"] for row in roster if row["average"] is not None]
        context = {
            "groups": groups,
            "pending": pending[:8],
            "pending_count": pending.count(),
            "upcoming": upcoming,
            "attendance_group": groups.first(),
            "roster": roster[:12],
            "class_average": round(sum(class_avgs) / len(class_avgs), 1) if class_avgs else None,
            "risk_count": sum(1 for row in roster if row["risk"]),
            "class_charts": _class_charts(roster),
        }
        return render(request, "dashboards/teacher.html", context)

    groups = scoped_groups(user)
    progress = assignment_progress(user)
    homework = Assignment.objects.filter(group__in=groups, is_published=True).order_by("-created_at")[:5]
    submissions = Submission.objects.filter(student=user).select_related("assignment")[:5]
    context = {
        "groups": groups,
        "homework": homework,
        "submissions": submissions,
        "cards": [
            {"label": "Мои группы", "value": groups.count(), "href": "web:groups"},
            {"label": "Домашние задания", "value": progress["pending"], "hint": "ждут сдачи", "href": "web:homework"},
            {"label": "Средний балл", "value": average_score(user) or "—"},
            {"label": "Посещаемость", "value": f"{attendance_percent(user) or 0}%"},
        ],
        "progress": progress,
        "attendance": attendance_percent(user),
        "average": average_score(user),
    }
    return render(request, "dashboards/student.html", context)


def _groups_with_lecture_streams(qs):
    from apps.attendance.models import LectureStream

    streams = LectureStream.objects.filter(is_active=True).select_related("lector").order_by("name")
    return qs.prefetch_related(Prefetch("lecture_streams", queryset=streams, to_attr="active_lecture_streams"))


@login_required
def group_list(request):
    groups = _groups_with_lecture_streams(scoped_groups(request.user))
    cards = []
    for group in groups:
        cards.append({"group": group, "kpis": group_kpis(group)})
    return render(request, "groups/list.html", {"cards": cards})


@login_required
def group_create(request):
    _require_roles(request.user, "admin")
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save()
        messages.success(request, "Группа создана.")
        return redirect("web:group-detail", pk=group.pk)
    return render(request, "groups/form.html", {"form": form, "title": "Новая группа"})


@login_required
def group_edit(request, pk):
    _require_roles(request.user, "admin")
    group = get_object_or_404(Group, pk=pk)
    form = GroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Группа обновлена.")
        return redirect("web:group-detail", pk=group.pk)
    return render(request, "groups/form.html", {"form": form, "title": "Редактирование группы", "group": group})


@login_required
def group_detail(request, pk):
    group = get_object_or_404(_groups_with_lecture_streams(scoped_groups(request.user)), pk=pk)
    students = User.objects.filter(enrollments__group=group).distinct()
    student_rows = [{"student": student, **student_stats(student, group)} for student in students]
    if request.method == "POST" and request.user.is_admin:
        action = request.POST.get("action")
        student_id = request.POST.get("student_id")
        if action == "enroll" and student_id:
            Enrollment.objects.get_or_create(group=group, student_id=student_id)
            messages.success(request, "Ученик добавлен в группу.")
        if action == "remove" and student_id:
            Enrollment.objects.filter(group=group, student_id=student_id).delete()
            messages.info(request, "Ученик исключён из группы.")
        return redirect("web:group-detail", pk=group.pk)
    available = User.objects.filter(role=User.Role.STUDENT, is_active=True).exclude(enrollments__group=group).prefetch_related("enrollments__group")
    return render(
        request,
        "groups/detail.html",
        {
            "group": group,
            "students": students,
            "student_rows": student_rows,
            "kpis": group_kpis(group),
            "assignments": group.assignments.all()[:6],
            "tests": group.tests.all()[:6],
            "available": available,
        },
    )


def _lesson_date(request, key="date"):
    raw = request.GET.get(key) or request.POST.get("lesson_date") or timezone.localdate().isoformat()
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return timezone.localdate()


def _parse_posted_date(raw):
    try:
        return date.fromisoformat(str(raw or "")[:10])
    except ValueError:
        return None


def _safe_app_path(raw: str) -> str:
    text = (raw or "").strip()
    if not text.startswith("/app/") or text.startswith("//") or "\\" in text or "\n" in text or "\r" in text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        return ""
    return text


def _parse_deadline(raw: str):
    text = (raw or "").strip()
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None and len(text) >= 16:
        parsed = parse_datetime(text[:16] + ":00")
    if parsed is None:
        return False
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _lesson_day_rows(group, current: date):
    stats = (
        Attendance.objects.filter(group=group, kind=Attendance.Kind.CLASS)
        .values("lesson_date")
        .annotate(
            present=Count("id", filter=Q(status=Attendance.Status.PRESENT)),
            absent=Count("id", filter=Q(status=Attendance.Status.ABSENT)),
        )
        .order_by("-lesson_date")
    )
    days = list(stats[:48])
    if current not in {row["lesson_date"] for row in days}:
        days.append({"lesson_date": current, "present": 0, "absent": 0})
        days.sort(key=lambda row: row["lesson_date"], reverse=True)
    return days


def _lecture_day_rows(stream, current: date | None):
    days = list(
        LectureSession.objects.filter(stream=stream)
        .annotate(
            present=Count(
                "attendance_records",
                filter=Q(attendance_records__status=LectureAttendance.Status.PRESENT),
            ),
            absent=Count(
                "attendance_records",
                filter=Q(attendance_records__status=LectureAttendance.Status.ABSENT),
            ),
        )
        .order_by("-date")[:48]
    )
    if current and current not in {row.date for row in days}:
        placeholder = LectureSession(stream=stream, date=current, topic="")
        placeholder.present = 0
        placeholder.absent = 0
        placeholder.unsaved = True
        days.append(placeholder)
        days.sort(key=lambda row: row.date, reverse=True)
    return days


def _group_mark_rows(rows):
    buckets: dict[str, list] = {}
    for row in rows:
        label = ", ".join(group.name for group in row["groups"]) or "Без группы"
        buckets.setdefault(label, []).append(row)
    grouped = []
    for name in sorted(buckets):
        people = sorted(buckets[name], key=lambda item: (item["student"].last_name, item["student"].first_name))
        grouped.append({"name": name, "rows": people})
    return grouped


@login_required
def group_attendance(request, pk):
    if request.user.is_lector and not request.user.is_teacher and not request.user.is_admin:
        raise PermissionDenied(_("Недостаточно прав."))
    _require_roles(request.user, "admin", "teacher")
    group = get_object_or_404(scoped_groups(request.user), pk=pk)
    lesson_date = _lesson_date(request)
    students = (
        User.objects.filter(enrollments__group=group, is_active=True)
        .distinct()
        .order_by("last_name", "first_name")
    )
    existing = {
        rec.student_id: rec.status
        for rec in Attendance.objects.filter(group=group, lesson_date=lesson_date, kind=Attendance.Kind.CLASS)
    }
    session = AttendanceSession.objects.filter(group=group, lesson_date=lesson_date, is_open=True).first()
    action = request.POST.get("action")
    if request.method == "POST" and action == "move":
        new_date = _parse_posted_date(request.POST.get("new_date"))
        back = f"{request.path}?date={lesson_date.isoformat()}"
        if not new_date:
            messages.error(request, "Укажите новую дату занятия.")
            return redirect(back)
        if new_date == lesson_date:
            messages.info(request, "Это уже дата этого занятия.")
            return redirect(back)
        clash = Attendance.objects.filter(group=group, lesson_date=new_date, kind=Attendance.Kind.CLASS).exists()
        session_clash = AttendanceSession.objects.filter(group=group, lesson_date=new_date).exists()
        if clash or session_clash:
            messages.error(request, "На эту дату уже есть посещаемость. Откройте её в списке слева.")
            return redirect(back)
        Attendance.objects.filter(group=group, lesson_date=lesson_date, kind=Attendance.Kind.CLASS).update(lesson_date=new_date)
        AttendanceSession.objects.filter(group=group, lesson_date=lesson_date).update(lesson_date=new_date)
        messages.success(request, "Дата занятия перенесена. Отметки остались на учениках.")
        return redirect(f"{request.path}?date={new_date.isoformat()}")
    if request.method == "POST" and action == "open":
        session = AttendanceSession.start(group, request.user, lesson_date)
        messages.success(request, "Сбор посещаемости открыт. Отправьте ссылку в чат группы.")
        return redirect(f"{request.path}?date={lesson_date.isoformat()}")
    if request.method == "POST" and action == "close" and session:
        session.is_open = False
        session.closed_at = timezone.now()
        session.save(update_fields=["is_open", "closed_at"])
        for student in students:
            Attendance.objects.get_or_create(
                student=student,
                group=group,
                lesson_date=lesson_date,
                kind=Attendance.Kind.CLASS,
                defaults={"status": Attendance.Status.ABSENT, "marked_by": request.user},
            )
        messages.success(request, "Сбор закрыт. Кто не отметился — отмечены как отсутствующие.")
        return redirect(f"{request.path}?date={lesson_date.isoformat()}")
    if request.method == "POST" and action in {"", "save", None}:
        allowed = {Attendance.Status.PRESENT, Attendance.Status.ABSENT}
        for student in students:
            status_value = request.POST.get(f"status_{student.id}")
            if status_value == "clear":
                Attendance.objects.filter(
                    student=student,
                    group=group,
                    lesson_date=lesson_date,
                    kind=Attendance.Kind.CLASS,
                ).delete()
                continue
            if status_value not in allowed:
                continue
            Attendance.objects.update_or_create(
                student=student,
                group=group,
                lesson_date=lesson_date,
                kind=Attendance.Kind.CLASS,
                defaults={"status": status_value, "marked_by": request.user},
            )
        messages.success(request, "Посещаемость сохранена, проценты пересчитаны.")
        return redirect(f"{request.path}?date={lesson_date.isoformat()}")

    if not session and lesson_date == timezone.localdate():
        had_closed = AttendanceSession.objects.filter(group=group, lesson_date=lesson_date, is_open=False).exists()
        if not had_closed:
            session = AttendanceSession.start(group, request.user, lesson_date)

    present_ids = {
        rec.student_id
        for rec in Attendance.objects.filter(
            group=group, lesson_date=lesson_date, kind=Attendance.Kind.CLASS, status=Attendance.Status.PRESENT
        )
    }
    checkins = [student for student in students if student.id in present_ids]
    rows = [
        {"student": student, "status": existing.get(student.id, "")}
        for student in students
    ]
    checkin_url = request.build_absolute_uri(reverse("web:attendance-checkin", args=[session.token])) if session else ""
    present_marked = len(checkins)
    absent_marked = sum(1 for row in rows if row["status"] == Attendance.Status.ABSENT)
    saved_days = []
    bucket = None
    saved_records = (
        Attendance.objects.filter(group=group, kind=Attendance.Kind.CLASS)
        .select_related("student")
        .order_by("-lesson_date", "student__last_name", "student__first_name")
    )
    for record in saved_records:
        if bucket is None or bucket["date"] != record.lesson_date:
            if len(saved_days) >= 30:
                break
            bucket = {"date": record.lesson_date, "records": [], "present": 0, "absent": 0}
            saved_days.append(bucket)
        bucket["records"].append(record)
        if record.status == Attendance.Status.PRESENT:
            bucket["present"] += 1
        else:
            bucket["absent"] += 1
    peer_groups = (
        scoped_groups(request.user)
        .filter(is_active=True)
        .select_related("language", "teacher")
        .annotate(student_count=Count("enrollments", distinct=True))
        .order_by("name")
    )
    return render(
        request,
        "groups/attendance.html",
        {
            "group": group,
            "rows": rows,
            "lesson_date": lesson_date.isoformat(),
            "lesson_on": lesson_date,
            "saved_days": saved_days,
            "session": session,
            "checkins": checkins,
            "checkin_url": checkin_url,
            "present_count": present_marked,
            "absent_marked": absent_marked,
            "open_marked": len(rows) - present_marked - absent_marked,
            "student_count": len(rows),
            "peer_groups": peer_groups,
        },
    )


@login_required
def group_attendance_live(request, pk):
    if request.user.is_lector and not request.user.is_teacher and not request.user.is_admin:
        raise PermissionDenied(_("Недостаточно прав."))
    _require_roles(request.user, "admin", "teacher")
    group = get_object_or_404(scoped_groups(request.user), pk=pk)
    raw_date = request.GET.get("date") or timezone.localdate().isoformat()
    try:
        lesson_date = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        lesson_date = date.today()
    students = User.objects.filter(enrollments__group=group).order_by("last_name", "first_name")
    present_ids = set(
        Attendance.objects.filter(
            group=group,
            lesson_date=lesson_date,
            kind=Attendance.Kind.CLASS,
            status=Attendance.Status.PRESENT,
        ).values_list("student_id", flat=True)
    )
    checkins = [student for student in students if student.id in present_ids]
    return render(
        request,
        "groups/_checkins.html",
        {"checkins": checkins, "present_count": len(checkins), "student_count": students.count()},
    )


@login_required
def lecture_stream_list(request):
    if not (request.user.is_admin or request.user.can_manage_lectures):
        raise PermissionDenied(_("Недостаточно прав."))
    streams = scoped_lecture_streams(request.user).filter(is_active=True).prefetch_related("groups", "lector")
    return render(request, "lectures/list.html", {"streams": streams})


@login_required
def lecture_stream_create(request):
    _require_roles(request.user, "admin")
    if request.method == "POST":
        form = LectureStreamForm(request.POST)
        if form.is_valid():
            stream = form.save()
            messages.success(request, "Поток лекций создан.")
            return redirect("web:lecture-stream-detail", pk=stream.pk)
    else:
        form = LectureStreamForm()
    return render(request, "lectures/form.html", {"form": form, "title": "Новый поток лекций"})


@login_required
def lecture_stream_edit(request, pk):
    _require_roles(request.user, "admin")
    stream = get_object_or_404(LectureStream, pk=pk)
    if request.method == "POST":
        form = LectureStreamForm(request.POST, instance=stream)
        if form.is_valid():
            form.save()
            messages.success(request, "Поток лекций обновлён.")
            return redirect("web:lecture-stream-detail", pk=stream.pk)
    else:
        form = LectureStreamForm(instance=stream)
    return render(request, "lectures/form.html", {"form": form, "title": "Редактирование потока", "stream": stream})


@login_required
def lecture_stream_detail(request, pk):
    stream = get_object_or_404(scoped_lecture_streams(request.user), pk=pk)
    sessions = stream.sessions.select_related("stream").order_by("-date")[:80]
    return render(
        request,
        "lectures/detail.html",
        {"stream": stream, "sessions": sessions},
    )


@login_required
def lecture_session_create(request, stream_pk):
    _require_roles(request.user, "admin")
    stream = get_object_or_404(LectureStream, pk=stream_pk)
    if request.method == "POST":
        form = LectureSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.stream = stream
            session.save()
            messages.success(request, "Лекция добавлена в расписание.")
            return redirect("web:lecture-stream-detail", pk=stream.pk)
    else:
        form = LectureSessionForm()
    return render(
        request,
        "lectures/session_form.html",
        {"form": form, "stream": stream, "title": "Новая лекция"},
    )


@login_required
def lecture_session_edit(request, pk):
    _require_roles(request.user, "admin")
    session = get_object_or_404(LectureSession.objects.select_related("stream"), pk=pk)
    if request.method == "POST":
        form = LectureSessionForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            messages.success(request, "Лекция обновлена.")
            return redirect("web:lecture-stream-detail", pk=session.stream_id)
    else:
        form = LectureSessionForm(instance=session)
    return render(
        request,
        "lectures/session_form.html",
        {"form": form, "stream": session.stream, "title": "Редактирование лекции", "session": session},
    )


@login_required
def lecture_attendance(request):
    if not (request.user.is_admin or request.user.can_manage_lectures):
        raise PermissionDenied(_("Недостаточно прав."))
    streams = scoped_lecture_streams(request.user).filter(is_active=True)
    stream_pk = request.GET.get("stream") or request.POST.get("stream_id")
    session_pk = request.GET.get("session") or request.POST.get("session_id")
    stream = None
    lesson_date = None
    if stream_pk:
        stream = get_object_or_404(streams, pk=stream_pk)
    if session_pk:
        legacy = get_object_or_404(
            LectureSession.objects.filter(stream__in=streams, is_cancelled=False).select_related("stream"),
            pk=session_pk,
        )
        return redirect(f"{request.path}?stream={legacy.stream_id}&date={legacy.date.isoformat()}")
    if stream:
        lesson_date = _lesson_date(request)

    lecture_session = None
    if stream and lesson_date:
        lecture_session = resolve_lecture_session(stream, lesson_date, create=False)

    checkin = None
    if stream and lesson_date:
        checkin = LectureCheckInSession.objects.filter(stream=stream, lesson_date=lesson_date, is_open=True).first()

    if request.method == "POST" and stream and lesson_date:
        action = request.POST.get("action")
        posted_group = (request.POST.get("group_id") or "").strip()

        def lecture_redirect(day):
            url = f"{request.path}?stream={stream.pk}&date={day.isoformat()}"
            if posted_group:
                url += f"&group={posted_group}"
            return url

        redirect_url = lecture_redirect(lesson_date)
        if action == "move":
            new_date = _parse_posted_date(request.POST.get("new_date"))
            source_checkins = LectureCheckInSession.objects.filter(stream=stream, lesson_date=lesson_date)
            if not lecture_session and not source_checkins.exists():
                messages.error(request, "Сначала сохраните посещаемость — тогда дату можно перенести вместе с отметками.")
                return redirect(redirect_url)
            if not new_date:
                messages.error(request, "Укажите новую дату занятия.")
                return redirect(redirect_url)
            if new_date == lesson_date:
                messages.info(request, "Это уже дата этого занятия.")
                return redirect(redirect_url)
            taken = False
            if lecture_session:
                taken = LectureSession.objects.filter(stream=stream, date=new_date).exclude(pk=lecture_session.pk).exists()
            else:
                taken = LectureSession.objects.filter(stream=stream, date=new_date).exists()
            checkin_taken = LectureCheckInSession.objects.filter(stream=stream, lesson_date=new_date).exists()
            if taken or checkin_taken:
                messages.error(request, "На эту дату лекция уже есть.")
                return redirect(redirect_url)
            if lecture_session:
                lecture_session.date = new_date
                lecture_session.save(update_fields=["date"])
            source_checkins.update(lesson_date=new_date)
            messages.success(request, "Дата лекции перенесена вместе с отметками.")
            return redirect(lecture_redirect(new_date))
        if action == "open":
            LectureCheckInSession.start(stream, request.user, lesson_date)
            messages.success(request, "Сбор посещаемости открыт. Отправьте ссылку или QR в чат.")
            return redirect(redirect_url)
        if action == "close" and checkin:
            checkin.is_open = False
            checkin.closed_at = timezone.now()
            checkin.save(update_fields=["is_open", "closed_at"])
            lecture_session = resolve_lecture_session(stream, lesson_date, create=True)
            present_ids = lecture_present_student_ids(stream, lesson_date)
            for row in stream_student_rows(stream):
                student = row["student"]
                if student.pk in present_ids:
                    continue
                LectureAttendance.objects.update_or_create(
                    session=lecture_session,
                    student=student,
                    defaults={"status": LectureAttendance.Status.ABSENT, "marked_by": request.user},
                )
            messages.success(request, "Сбор закрыт. Кто не отметился — отмечены как отсутствующие.")
            return redirect(redirect_url)
        if action in {"save", "", None}:
            topic = (request.POST.get("topic") or "").strip()
            lecture_session = resolve_lecture_session(stream, lesson_date, topic=topic, create=True)
            if topic:
                lecture_session.topic = topic
                lecture_session.save(update_fields=["topic"])
            allowed = {LectureAttendance.Status.PRESENT, LectureAttendance.Status.ABSENT}
            for row in stream_student_rows(stream):
                student = row["student"]
                status_value = request.POST.get(f"status_{student.pk}")
                if status_value == "clear":
                    if lecture_session:
                        LectureAttendance.objects.filter(session=lecture_session, student=student).delete()
                    continue
                if status_value not in allowed:
                    continue
                LectureAttendance.objects.update_or_create(
                    session=lecture_session,
                    student=student,
                    defaults={"status": status_value, "marked_by": request.user},
                )
            messages.success(request, "Посещаемость лекции сохранена, проценты пересчитаны.")
            return redirect(redirect_url)

    if stream and lesson_date and not checkin and lesson_date == timezone.localdate():
        had_closed = LectureCheckInSession.objects.filter(
            stream=stream, lesson_date=lesson_date, is_open=False
        ).exists()
        if not had_closed:
            checkin = LectureCheckInSession.start(stream, request.user, lesson_date)

    rows = []
    student_rows = stream_student_rows(stream) if stream and lesson_date else []
    present_ids = lecture_present_student_ids(stream, lesson_date) if stream and lesson_date else set()
    checkins = [row["student"] for row in student_rows if row["student"].pk in present_ids]
    if stream and lesson_date:
        existing = {}
        if lecture_session:
            existing = {rec.student_id: rec.status for rec in lecture_session.attendance_records.all()}
        for row in student_rows:
            status = existing.get(row["student"].pk, "")
            row["status"] = status
            rows.append(row)

    stream_groups = []
    selected_group = None
    show_all = False
    if stream:
        stream_groups = list(
            stream.groups.filter(is_active=True)
            .annotate(student_count=Count("enrollments", distinct=True))
            .order_by("name")
        )
        raw_group = (request.GET.get("group") or request.POST.get("group_id") or "").strip()
        show_all = raw_group == "all"
        if raw_group.isdigit():
            selected_group = next((item for item in stream_groups if item.pk == int(raw_group)), None)
        elif not show_all and len(stream_groups) == 1:
            selected_group = stream_groups[0]
    show_roster = bool(show_all or selected_group or not stream_groups)
    if selected_group:
        rows = [row for row in rows if any(item.pk == selected_group.pk for item in row["groups"])]
        allowed_ids = {row["student"].pk for row in rows}
        checkins = [person for person in checkins if person.pk in allowed_ids]
    if not show_roster:
        rows = []
        checkins = []
    present_count = sum(1 for row in rows if row["status"] == LectureAttendance.Status.PRESENT)

    checkin_url = (
        request.build_absolute_uri(reverse("web:lecture-checkin", args=[checkin.token])) if checkin else ""
    )
    absent_marked = sum(1 for row in rows if row["status"] == LectureAttendance.Status.ABSENT)
    return render(
        request,
        "attendance/lecture.html",
        {
            "streams": streams,
            "stream": stream,
            "lesson_date": lesson_date.isoformat() if lesson_date else "",
            "lesson_on": lesson_date,
            "lesson_days": _lecture_day_rows(stream, lesson_date) if stream else [],
            "topic": lecture_session.topic if lecture_session else "",
            "lecture_session": lecture_session,
            "rows": rows,
            "grouped_rows": _group_mark_rows(rows),
            "stream_groups": stream_groups,
            "selected_group": selected_group,
            "show_all": show_all,
            "show_roster": show_roster,
            "checkin": checkin,
            "checkin_url": checkin_url,
            "checkins": checkins,
            "present_count": present_count,
            "absent_marked": absent_marked,
            "open_marked": len(rows) - present_count - absent_marked,
            "student_count": len(rows),
        },
    )


@login_required
def lecture_attendance_live(request):
    if not (request.user.is_admin or request.user.can_manage_lectures):
        raise PermissionDenied(_("Недостаточно прав."))
    stream_pk = request.GET.get("stream")
    streams = scoped_lecture_streams(request.user).filter(is_active=True)
    stream = get_object_or_404(streams, pk=stream_pk)
    raw_date = request.GET.get("date") or timezone.localdate().isoformat()
    try:
        lesson_date = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        lesson_date = timezone.localdate()
    student_rows = stream_student_rows(stream)
    raw_group = (request.GET.get("group") or "").strip()
    if raw_group.isdigit():
        group_pk = int(raw_group)
        student_rows = [row for row in student_rows if any(item.pk == group_pk for item in row["groups"])]
    present_ids = lecture_present_student_ids(stream, lesson_date)
    checkins = [row["student"] for row in student_rows if row["student"].pk in present_ids]
    return render(
        request,
        "groups/_checkins.html",
        {
            "checkins": checkins,
            "present_count": len(checkins),
            "student_count": len(student_rows),
        },
    )


@login_required
def lecture_checkin(request, token):
    checkin = get_object_or_404(LectureCheckInSession, token=token.upper())
    if not checkin.is_open:
        return render(request, "attendance/lecture_checkin.html", {"status": "closed", "checkin": checkin})
    if not request.user.is_student:
        return render(request, "attendance/lecture_checkin.html", {"status": "not_student", "checkin": checkin})
    if not student_in_stream(request.user, checkin.stream):
        return render(
            request,
            "attendance/lecture_checkin.html",
            {"status": "not_enrolled", "checkin": checkin},
        )
    lecture_session = resolve_lecture_session(checkin.stream, checkin.lesson_date, create=True)
    LectureAttendance.objects.update_or_create(
        session=lecture_session,
        student=request.user,
        defaults={
            "status": LectureAttendance.Status.PRESENT,
            "marked_by": request.user,
        },
    )
    return render(request, "attendance/lecture_checkin.html", {"status": "ok", "checkin": checkin})


@login_required
def attendance_checkin(request, token):
    session = get_object_or_404(AttendanceSession, token=token.upper())
    if not session.is_open:
        return render(request, "attendance/checkin.html", {"status": "closed", "session": session})
    if not request.user.is_student:
        return render(request, "attendance/checkin.html", {"status": "not_student", "session": session})
    enrolled = Enrollment.objects.filter(student=request.user, group=session.group).exists()
    if not enrolled:
        return render(request, "attendance/checkin.html", {"status": "not_enrolled", "session": session})
    Attendance.objects.update_or_create(
        student=request.user,
        group=session.group,
        lesson_date=session.lesson_date,
        kind=Attendance.Kind.CLASS,
        defaults={
            "status": Attendance.Status.PRESENT,
            "comment": "Отметился по ссылке / QR",
            "marked_by": request.user,
        },
    )
    return render(request, "attendance/checkin.html", {"status": "ok", "session": session})


@login_required
def group_journal(request, pk):
    group = get_object_or_404(scoped_groups(request.user), pk=pk)
    rows = []
    for student in User.objects.filter(enrollments__group=group).distinct():
        progress = assignment_progress(student, group)
        rows.append(
            {
                "student": student,
                "attendance": attendance_percent(student, group),
                "average": average_score(student, group),
                "done": progress["done"],
                "pending": progress["pending"],
            }
        )
    return render(request, "groups/journal.html", {"group": group, "rows": rows, "kpis": group_kpis(group)})


@login_required
def export_group_attendance(request, pk):
    _require_roles(request.user, "admin", "teacher")
    group = get_object_or_404(scoped_groups(request.user), pk=pk)
    return export_attendance(group)


@login_required
def export_group_grades(request, pk):
    _require_roles(request.user, "admin", "teacher")
    group = get_object_or_404(scoped_groups(request.user), pk=pk)
    return export_grades(group)


@login_required
def teacher_journal(request):
    _require_roles(request.user, "admin", "teacher")
    groups = scoped_groups(request.user)
    start = timezone.localdate() - timedelta(days=30)
    lessons = (
        Attendance.objects.filter(group__in=groups, lesson_date__gte=start, kind=Attendance.Kind.CLASS)
        .values("group__name", "lesson_date")
        .distinct()
        .order_by("-lesson_date")
    )
    pending = Submission.objects.filter(assignment__group__in=groups, status=Submission.Status.SUBMITTED)
    return render(
        request,
        "journals/teacher.html",
        {
            "groups": groups,
            "lessons": lessons[:40],
            "pending": pending.select_related("student", "assignment", "reviewing_by")[:20],
            "assignments": Assignment.objects.filter(group__in=groups)[:10],
        },
    )


@login_required
def student_list(request):
    _require_roles(request.user, "admin", "teacher")
    query = request.GET.get("q", "").strip()
    qs = scoped_students(request.user)
    if query:
        qs = qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(login__icontains=query))
    students = []
    for student in qs.distinct()[:80]:
        stats = student_stats(student)
        students.append(
            {
                "user": student,
                "attendance": stats["attendance"],
                "average": stats["average"],
                "progress": stats["progress"],
                "risk": stats["risk"],
                "groups": student.enrollments.select_related("group", "group__teacher", "group__language"),
            }
        )
    return render(request, "users/students.html", {"students": students, "query": query})


@login_required
def teacher_list(request):
    _require_roles(request.user, "admin")
    teachers = User.objects.filter(role=User.Role.TEACHER, is_active=True).prefetch_related(
        "teaching_groups__language", "assistants", "lecture_streams"
    )
    lectors = User.objects.filter(role=User.Role.LECTOR, is_active=True).prefetch_related("lecture_streams")
    return render(request, "users/teachers.html", {"teachers": teachers, "lectors": lectors})


@login_required
def admin_list(request):
    _require_primary_admin(request.user)
    admins = User.objects.filter(role=User.Role.ADMIN).order_by("-is_primary_admin", "last_name", "login")
    return render(request, "users/admins.html", {"admins": admins})


@login_required
def admin_create(request):
    _require_primary_admin(request.user)
    form = AdminCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        admin = form.save(commit=False)
        admin.role = User.Role.ADMIN
        admin.login = form.cleaned_data["login"]
        admin.is_primary_admin = False
        admin.is_staff = False
        admin.is_superuser = False
        admin.must_change_password = False
        admin.profile_completed = True
        admin.set_password(form.cleaned_data["password"])
        admin.save()
        _issue_credentials(request, admin, form.cleaned_data["password"])
        return redirect("web:user-detail", pk=admin.pk)
    return render(
        request,
        "users/form.html",
        {
            "form": form,
            "title": "Новый администратор",
            "lead": "Это второстепенный админ: он ведёт центр, но не может добавлять других администраторов. Все его действия видны вам в журнале.",
            "submit_label": "Создать администратора",
        },
    )


def _issue_credentials(request, person, password: str):
    request.session["issued_credentials"] = {"pk": person.pk, "login": person.login, "password": password}
    messages.success(request, _("Аккаунт создан. Логин и пароль показаны один раз — сохраните их."))


def _sync_student_groups(student, groups):
    selected = {group.pk for group in groups}
    Enrollment.objects.filter(student=student).exclude(group_id__in=selected).delete()
    for group in groups:
        Enrollment.objects.get_or_create(group=group, student=student)


@login_required
def teacher_create(request):
    _require_roles(request.user, "admin")
    form = TeacherCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        teacher = form.save(commit=False)
        teacher.role = User.Role.TEACHER
        teacher.login = form.cleaned_data["login"]
        teacher.must_change_password = False
        teacher.profile_completed = True
        teacher.set_password(form.cleaned_data["password"])
        teacher.save()
        _issue_credentials(request, teacher, form.cleaned_data["password"])
        return redirect("web:user-detail", pk=teacher.pk)
    return render(
        request,
        "users/form.html",
        {
            "form": form,
            "title": "Новый преподаватель",
            "lead": "Задайте логин и пароль — передайте их преподавателю. Потом он сможет сменить пароль в профиле.",
            "submit_label": "Создать преподавателя",
        },
    )


@login_required
def lector_create(request):
    _require_roles(request.user, "admin")
    form = LectorCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lector = form.save(commit=False)
        lector.role = User.Role.LECTOR
        lector.login = form.cleaned_data["login"]
        lector.must_change_password = False
        lector.profile_completed = True
        lector.set_password(form.cleaned_data["password"])
        lector.save()
        _issue_credentials(request, lector, form.cleaned_data["password"])
        return redirect("web:user-detail", pk=lector.pk)
    return render(
        request,
        "users/form.html",
        {
            "form": form,
            "title": "Новый лектор",
            "lead": "Отдельная учётка только для лекций. Преподавателя групп можно назначить ведущим в потоке без второго логина.",
            "submit_label": "Создать лектора",
        },
    )


@login_required
def assistant_create(request):
    _require_roles(request.user, "admin")
    form = AssistantCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        assistant = form.save(commit=False)
        assistant.role = User.Role.ASSISTANT
        assistant.login = form.cleaned_data["login"]
        assistant.lead_teacher = form.cleaned_data["lead_teacher"]
        assistant.must_change_password = False
        assistant.profile_completed = True
        assistant.set_password(form.cleaned_data["password"])
        assistant.save()
        _issue_credentials(request, assistant, form.cleaned_data["password"])
        return redirect("web:user-detail", pk=assistant.pk)
    return render(
        request,
        "users/form.html",
        {
            "form": form,
            "title": "Новый ассистент",
            "lead": "Ассистент работает только с группами выбранного преподавателя и не видит учеников из чужих групп.",
            "submit_label": "Создать ассистента",
        },
    )


@login_required
def user_create(request):
    _require_roles(request.user, "admin")
    form = StudentCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        student = form.save(commit=False)
        student.role = User.Role.STUDENT
        student.login = form.cleaned_data["login"]
        student.must_change_password = True
        student.profile_completed = False
        student.set_password(form.cleaned_data["password"])
        student.save()
        group = form.cleaned_data["group"]
        Enrollment.objects.get_or_create(group=group, student=student)
        _issue_credentials(request, student, form.cleaned_data["password"])
        return redirect("web:user-detail", pk=student.pk)
    return render(
        request,
        "users/form.html",
        {
            "form": form,
            "title": "Новый ученик",
            "lead": "Укажите логин, пароль, преподавателя и группу. При первом входе ученик сменит пароль и заполнит ФИО, факультет и курс.",
            "submit_label": "Создать ученика",
            "filter_groups": True,
        },
    )


@login_required
def user_edit(request, pk):
    _require_roles(request.user, "admin")
    person = get_object_or_404(User, pk=pk)
    if person.is_admin and not request.user.is_primary_admin:
        raise PermissionDenied(_("Редактировать администраторов может только главный админ."))
    form = UserEditForm(request.POST or None, instance=person, editor=request.user)
    if request.method == "POST" and form.is_valid():
        person = form.save(commit=False)
        password = form.cleaned_data.get("new_password")
        if password:
            person.set_password(password)
            person.must_change_password = person.is_student
        person.save()
        if person.role != User.Role.ADMIN:
            person.is_primary_admin = False
            person.is_superuser = False
            person.is_staff = False
            person.save(update_fields=["is_primary_admin", "is_superuser", "is_staff"])
        else:
            person.is_superuser = person.is_primary_admin
            person.is_staff = person.is_primary_admin
            person.save(update_fields=["is_superuser", "is_staff"])
        if person.is_student:
            _sync_student_groups(person, form.cleaned_data.get("groups") or [])
        else:
            Enrollment.objects.filter(student=person).delete()
        if password:
            _issue_credentials(request, person, password)
        else:
            messages.success(request, "Профиль обновлён.")
        return redirect("web:user-detail", pk=person.pk)
    return render(
        request,
        "users/form.html",
        {
            "form": form,
            "title": "Редактирование профиля",
            "person": person,
            "lead": "Для ученика можно сменить группы и преподавателей — отметьте нужные группы.",
            "submit_label": "Сохранить",
        },
    )


@login_required
def user_detail(request, pk):
    person = get_object_or_404(User, pk=pk)
    if request.user.is_student and request.user.pk != person.pk:
        raise PermissionDenied
    if request.user.is_teaching_staff and person.is_student:
        if not scoped_students(request.user).filter(pk=person.pk).exists():
            raise PermissionDenied
    if request.method == "POST" and request.user.is_admin and person.is_student:
        action = request.POST.get("action")
        group_id = request.POST.get("group_id")
        if action == "enroll" and group_id:
            group = get_object_or_404(Group, pk=group_id, is_active=True)
            Enrollment.objects.get_or_create(group=group, student=person)
            teacher_name = group.teacher.full_name if group.teacher else _("группе")
            messages.success(
                request,
                _("Ученик зачислен в «{group}» к {teacher}.", group=group.name, teacher=teacher_name),
            )
        if action == "remove" and group_id:
            Enrollment.objects.filter(group_id=group_id, student=person).delete()
            messages.info(request, "Ученик убран из группы.")
        return redirect("web:user-detail", pk=person.pk)
    progress = assignment_progress(person)
    issued = request.session.get("issued_credentials")
    if issued and issued.get("pk") != person.pk:
        issued = None
    elif issued:
        request.session.pop("issued_credentials", None)
    assigned_ids = list(person.enrollments.values_list("group_id", flat=True)) if person.is_student else []
    available_groups = (
        Group.objects.filter(is_active=True).select_related("language", "teacher").exclude(pk__in=assigned_ids)
        if person.is_student and request.user.is_admin
        else []
    )
    lecture_streams = []
    if person.is_teacher:
        groups = person.teaching_groups.select_related("language")
        lecture_streams = list(person.lecture_streams.filter(is_active=True))
    elif person.is_lector:
        groups = Group.objects.filter(
            lecture_streams__lector=person, lecture_streams__is_active=True
        ).select_related("language", "teacher").distinct()
        lecture_streams = list(person.lecture_streams.filter(is_active=True))
    elif person.is_assistant and person.lead_teacher_id:
        groups = person.lead_teacher.teaching_groups.select_related("language")
    else:
        groups = person.enrollments.select_related("group", "group__teacher", "group__language")
    return render(
        request,
        "users/detail.html",
        {
            "person": person,
            "attendance": attendance_percent(person),
            "average": average_score(person),
            "progress": progress,
            "groups": groups,
            "lecture_streams": lecture_streams,
            "submissions": Submission.objects.filter(student=person).select_related("assignment")[:8],
            "attempts": TestAttempt.objects.filter(student=person).select_related("test")[:8],
            "issued": issued,
            "available_groups": available_groups,
        },
    )


@login_required
def student_search(request):
    _require_roles(request.user, "admin", "teacher")
    query = request.GET.get("q", "").strip()
    qs = scoped_students(request.user)
    if query:
        qs = qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(login__icontains=query))
    return render(request, "partials/student_search.html", {"students": qs.distinct()[:12], "query": query})


def _iter_uploads(files):
    for uploaded in files:
        if uploaded and getattr(uploaded, "name", "") and getattr(uploaded, "size", 0):
            yield uploaded


def _read_upload_payloads(files):
    payloads = []
    for uploaded in _iter_uploads(files):
        payloads.append((uploaded.name, uploaded.read()))
    return payloads


def _store_homework_payloads(assignment, payloads):
    for name, content in payloads:
        AssignmentFile.objects.create(
            assignment=assignment,
            file=ContentFile(content, name=name),
            original_name=name,
        )


def _store_homework_files(assignment, files):
    _store_homework_payloads(assignment, _read_upload_payloads(files))


@login_required
def homework_list(request):
    user = request.user
    qs = Assignment.objects.select_related("group").prefetch_related("files")
    if user.is_teaching_staff:
        qs = qs.filter(group__in=scoped_groups(user))
    elif user.is_student:
        qs = qs.filter(group__enrollments__student=user, is_published=True)
    submissions = {
        item.assignment_id: item
        for item in Submission.objects.filter(student=user)
    } if user.is_student else {}
    return render(request, "homework/list.html", {"assignments": qs.distinct(), "submissions": submissions})


@login_required
def homework_create(request):
    _require_roles(request.user, "admin", "teacher")
    groups_qs = scoped_groups(request.user).filter(is_active=True)
    preset = []
    raw_group = request.GET.get("group")
    if raw_group:
        try:
            pk = int(raw_group)
        except (TypeError, ValueError):
            pk = None
        else:
            if groups_qs.filter(pk=pk).exists():
                preset = [pk]
    form = AssignmentForm(
        request.POST or None,
        request.FILES or None,
        group_queryset=groups_qs,
        multi_groups=True,
        initial_groups=preset,
    )
    if request.method == "POST" and form.is_valid():
        selected = list(form.cleaned_data["groups"])
        payloads = _read_upload_payloads(request.FILES.getlist("attachments"))
        created = []
        for group in selected:
            assignment = Assignment(
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description") or "",
                deadline=form.cleaned_data.get("deadline"),
                is_published=form.cleaned_data.get("is_published", True),
                group=group,
                created_by=request.user,
            )
            assignment.save()
            _store_homework_payloads(assignment, payloads)
            created.append(assignment)
        if len(created) == 1:
            messages.success(request, "Домашнее задание загружено.")
            return redirect("web:homework-detail", pk=created[0].pk)
        messages.success(request, _("Задание отправлено в {count} групп.", count=len(created)))
        return redirect("web:homework")
    if request.method == "GET" and not groups_qs.exists():
        messages.warning(request, "Сначала нужна группа — без неё задание некуда назначить.")
    return render(
        request,
        "homework/form.html",
        {"form": form, "title": "Загрузить домашнее задание", "multi_groups": True},
    )


@login_required
def homework_edit(request, pk):
    _require_roles(request.user, "admin", "teacher")
    assignment = get_object_or_404(Assignment.objects.prefetch_related("files"), pk=pk)
    if not request.user.is_admin and not can_access_group(request.user, assignment.group):
        raise PermissionDenied
    if request.method == "POST" and request.POST.get("delete_file"):
        AssignmentFile.objects.filter(pk=request.POST.get("delete_file"), assignment=assignment).delete()
        messages.success(request, "Файл удалён.")
        return redirect("web:homework-edit", pk=assignment.pk)
    form = AssignmentForm(
        request.POST or None,
        request.FILES or None,
        instance=assignment,
        group_queryset=scoped_groups(request.user),
        multi_groups=False,
    )
    if request.method == "POST" and not request.POST.get("delete_file") and form.is_valid():
        form.save()
        _store_homework_files(assignment, request.FILES.getlist("attachments"))
        messages.success(request, "Задание обновлено.")
        return redirect("web:homework-detail", pk=assignment.pk)
    return render(
        request,
        "homework/form.html",
        {"form": form, "title": "Редактирование задания", "assignment": assignment},
    )


@login_required
def homework_detail(request, pk):
    assignment = get_object_or_404(Assignment.objects.select_related("group").prefetch_related("files", "items"), pk=pk)
    if not request.user.is_admin and not scoped_groups(request.user).filter(pk=assignment.group_id).exists():
        raise PermissionDenied
    if request.user.is_student and not assignment.is_published:
        raise PermissionDenied
    if request.method == "POST" and request.POST.get("action") == "deadline":
        if not (request.user.is_admin or request.user.is_teaching_staff):
            raise PermissionDenied
        if not request.user.is_admin and not can_access_group(request.user, assignment.group):
            raise PermissionDenied
        parsed = _parse_deadline(request.POST.get("deadline"))
        back = _safe_app_path(request.POST.get("next")) or reverse("web:homework-detail", args=[assignment.pk])
        if parsed is False:
            messages.error(request, "Не получилось прочитать дату дедлайна.")
            return redirect(back)
        assignment.deadline = parsed
        assignment.save(update_fields=["deadline", "updated_at"])
        messages.success(request, "Дедлайн обновлён.")
        return redirect(back)
    submission = None
    if request.user.is_student:
        submission = Submission.objects.prefetch_related("files").filter(assignment=assignment, student=request.user).first()
    submissions = assignment.submissions.select_related("student", "reviewing_by") if not request.user.is_student else []
    if request.headers.get("HX-Request") and not request.user.is_student:
        return render(request, "homework/_submissions.html", {"assignment": assignment, "submissions": submissions})
    return render(
        request,
        "homework/detail.html",
        {"assignment": assignment, "submission": submission, "submissions": submissions},
    )


@login_required
@require_http_methods(["POST"])
def homework_submit(request, pk):
    _require_roles(request.user, "student")
    assignment = get_object_or_404(Assignment, pk=pk, is_published=True)
    if not scoped_groups(request.user).filter(pk=assignment.group_id).exists():
        raise PermissionDenied
    submission = Submission.objects.filter(assignment=assignment, student=request.user).first()
    if submission and submission.status == Submission.Status.GRADED:
        messages.info(request, "Эта работа уже проверена.")
        return redirect("web:homework-detail", pk=pk)
    answer = (request.POST.get("answer") or "").strip()
    answers = {}
    for item in assignment.items.all():
        answers[str(item.id)] = request.POST.get(f"item_{item.id}", "")
    uploads = list(_iter_uploads(request.FILES.getlist("files")))
    if not uploads and not answer and not (submission and submission.files.exists()):
        messages.error(request, "Прикрепите файл работы или напишите комментарий.")
        return redirect("web:homework-detail", pk=pk)
    if submission is None:
        submission = Submission(assignment=assignment, student=request.user)
    submission.answer = answer
    submission.answers = answers
    submission.status = Submission.Status.SUBMITTED
    submission.submitted_at = timezone.now()
    submission.save()
    for uploaded in uploads:
        SubmissionFile.objects.create(submission=submission, file=uploaded, original_name=uploaded.name)
    messages.success(request, "Работа отправлена на проверку.")
    return redirect("web:homework-detail", pk=pk)


@login_required
def submission_review(request, pk):
    _require_roles(request.user, "admin", "teacher")
    submission = get_object_or_404(
        Submission.objects.select_related("assignment__group", "student", "reviewing_by").prefetch_related("files"),
        pk=pk,
    )
    if not request.user.is_admin and not can_access_group(request.user, submission.assignment.group):
        raise PermissionDenied
    if request.method == "POST":
        if submission.lock_active() and submission.reviewing_by_id != request.user.pk:
            messages.error(request, _("Эту работу сейчас проверяет {name}.", name=submission.reviewing_by.full_name))
            return redirect("web:homework-detail", pk=submission.assignment_id)
        if request.POST.get("return_for_revision"):
            submission.status = Submission.Status.RETURNED
            submission.score = None
            submission.feedback = request.POST.get("feedback", "")
        else:
            raw = (request.POST.get("score") or "").replace(",", ".").strip()
            try:
                score = float(raw)
            except ValueError:
                messages.error(request, "Укажите оценку от 0 до 100.")
                return render(
                    request,
                    "homework/review.html",
                    {"submission": submission, "claimed": True, "locked_by": None},
                )
            submission.status = Submission.Status.GRADED
            submission.score = max(0.0, min(100.0, score))
            submission.feedback = request.POST.get("feedback", "")
            submission.graded_at = timezone.now()
            submission.graded_by = request.user
        submission.reviewing_by = None
        submission.reviewing_at = None
        submission.save()
        messages.success(request, "Проверка сохранена.")
        return redirect("web:homework-detail", pk=submission.assignment_id)
    if submission.status == Submission.Status.GRADED:
        claimed = True
        locked_by = None
    else:
        claimed = submission.claim_review(request.user)
        locked_by = None if claimed else submission.reviewing_by
    return render(
        request,
        "homework/review.html",
        {"submission": submission, "claimed": claimed, "locked_by": locked_by},
    )


@login_required
@require_http_methods(["POST"])
def submission_review_lock(request, pk):
    _require_roles(request.user, "admin", "teacher")
    submission = get_object_or_404(Submission.objects.select_related("assignment", "reviewing_by"), pk=pk)
    if not request.user.is_admin and not can_access_group(request.user, submission.assignment.group):
        raise PermissionDenied
    action = request.POST.get("action") or "ping"
    if action == "release":
        submission.release_review(request.user)
        return JsonResponse({"ok": True, "state": "pending"})
    if submission.touch_review(request.user) or submission.claim_review(request.user):
        return JsonResponse({"ok": True, "state": "checking"})
    who = submission.reviewing_by.full_name if submission.reviewing_by_id else ""
    return JsonResponse({"ok": False, "state": "checking", "by": who}, status=409)


@login_required
def test_list(request):
    retired = _redirect_retired_assessments(request.user)
    if retired:
        return retired
    user = request.user
    qs = Test.objects.select_related("group", "group__language")
    if user.is_student:
        qs = qs.filter(group__enrollments__student=user, is_published=True)
    attempts = {item.test_id: item for item in TestAttempt.objects.filter(student=user)} if user.is_student else {}
    return render(request, "tests/list.html", {"tests": qs.distinct(), "attempts": attempts})


@login_required
def test_create(request):
    return redirect("web:homework-create")


@login_required
def test_edit(request, pk):
    return redirect("web:homework-create")


@login_required
def test_detail(request, pk):
    retired = _redirect_retired_assessments(request.user)
    if retired:
        return retired
    test = get_object_or_404(
        Test.objects.select_related("group__language").prefetch_related("sections", "questions"), pk=pk
    )
    if test.group not in scoped_groups(request.user) and not request.user.is_admin:
        raise PermissionDenied
    attempt = TestAttempt.objects.filter(test=test, student=request.user).first() if request.user.is_student else None
    attempts = test.attempts.select_related("student") if not request.user.is_student else []
    return render(
        request,
        "tests/detail.html",
        {"test": test, "attempt": attempt, "attempts": attempts, "exam": test.exam_profile},
    )


@login_required
def test_take(request, pk):
    retired = _redirect_retired_assessments(request.user)
    if retired:
        return retired
    _require_roles(request.user, "student")
    test = get_object_or_404(
        Test.objects.select_related("group__language").prefetch_related("sections__questions", "questions"),
        pk=pk,
        is_published=True,
    )
    attempt, _ = TestAttempt.objects.get_or_create(test=test, student=request.user)
    if attempt.status == TestAttempt.Status.GRADED:
        messages.info(request, "Этот тест уже пройден.")
        return redirect("web:test-detail", pk=pk)
    if request.method == "POST":
        answers = {}
        for question in test.questions.all():
            items = (question.payload or {}).get("items") or []
            if items:
                answers[str(question.id)] = [request.POST.get(f"q_{question.id}_{index}", "") for index in range(len(items))]
            elif question.type == Question.Type.MULTIPLE:
                answers[str(question.id)] = request.POST.getlist(f"q_{question.id}")
            elif question.type in {Question.Type.MATCH, Question.Type.HEADING}:
                pairs = {}
                for key in (question.payload or {}).get("left", []):
                    pairs[key] = request.POST.get(f"q_{question.id}_{key}", "")
                answers[str(question.id)] = pairs
            else:
                answers[str(question.id)] = request.POST.get(f"q_{question.id}", "")
        grade_attempt(attempt, answers)
        messages.success(request, "Тест отправлен.")
        return redirect("web:test-detail", pk=pk)
    grouped = []
    nav = []
    number = 1

    def pack(question, start):
        span = question.span
        payload = question.payload or {}
        return {
            "question": question,
            "number": start,
            "end": start + span - 1,
            "span": span,
            "notes_html": render_notes_html(payload.get("body") or "", f"q_{question.id}", start)
            if question.is_notes
            else "",
        }

    for section in test.sections.all():
        items = []
        for question in section.questions.all():
            packed = pack(question, number)
            items.append(packed)
            for index in range(packed["span"]):
                nav.append({"n": number + index, "qid": question.id})
            number += packed["span"]
        grouped.append({"section": section, "questions": items})
    loose_qs = [question for question in test.questions.all() if question.section_id is None]
    if loose_qs:
        items = []
        for question in loose_qs:
            packed = pack(question, number)
            items.append(packed)
            for index in range(packed["span"]):
                nav.append({"n": number + index, "qid": question.id})
            number += packed["span"]
        grouped.append({"section": None, "questions": items})
    if not grouped:
        items = []
        for question in test.questions.all():
            packed = pack(question, number)
            items.append(packed)
            for index in range(packed["span"]):
                nav.append({"n": number + index, "qid": question.id})
            number += packed["span"]
        grouped = [{"section": None, "questions": items}]
    return render(
        request,
        "tests/take.html",
        {"test": test, "attempt": attempt, "grouped": grouped, "exam": test.exam_profile, "qnav": nav},
    )


@login_required
def exercise_list(request):
    retired = _redirect_retired_assessments(request.user)
    if retired:
        return retired
    qs = Exercise.objects.select_related("language")
    if request.user.is_student:
        qs = qs.filter(is_published=True)
    language = request.GET.get("language")
    kind = request.GET.get("type")
    if language:
        qs = qs.filter(language_id=language)
    if kind:
        qs = qs.filter(type=kind)
    attempts = {}
    if request.user.is_student:
        for item in ExerciseAttempt.objects.filter(student=request.user).order_by("-completed_at"):
            attempts.setdefault(item.exercise_id, item)
    return render(
        request,
        "practice/list.html",
        {"exercises": qs, "attempts": attempts, "languages": scoped_groups(request.user)},
    )


@login_required
def exercise_create(request):
    if request.user.is_teaching_staff:
        return redirect("web:homework-create")
    _require_roles(request.user, "admin")
    form = ExerciseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        exercise = form.save(commit=False)
        exercise.created_by = request.user
        raw = request.POST.get("content_json") or "{}"
        try:
            exercise.content = json.loads(raw)
        except json.JSONDecodeError:
            messages.error(request, "Некорректный JSON содержимого упражнения.")
            return render(request, "practice/form.html", {"form": form})
        exercise.save()
        messages.success(request, "Упражнение сохранено.")
        return redirect("web:exercise-detail", pk=exercise.pk)
    return render(request, "practice/form.html", {"form": form})


@login_required
def exercise_detail(request, pk):
    retired = _redirect_retired_assessments(request.user)
    if retired:
        return retired
    exercise = get_object_or_404(Exercise, pk=pk)
    last = ExerciseAttempt.objects.filter(exercise=exercise, student=request.user).first()
    if request.method == "POST" and request.user.is_student:
        answers = _collect_exercise_answers(request, exercise)
        score = grade_exercise(exercise, answers)
        ExerciseAttempt.objects.create(exercise=exercise, student=request.user, answers=answers, score=score)
        messages.success(request, _("Упражнение отправлено. Результат: {score}.", score=score if score is not None else _("на проверке")))
        return redirect("web:exercise-detail", pk=pk)
    return render(request, "practice/detail.html", {"exercise": exercise, "last": last})


def _collect_exercise_answers(request, exercise):
    content = exercise.content or {}
    if exercise.type in {Exercise.Type.VOCABULARY, Exercise.Type.GRAMMAR}:
        return request.POST.get("answer", "")
    if exercise.type == Exercise.Type.MATCHING:
        pairs = {}
        for left, _right in content.get("pairs", []):
            pairs[left] = request.POST.get(f"pair_{left}", "")
        return pairs
    if exercise.type == Exercise.Type.SENTENCE:
        return request.POST.getlist("words") or request.POST.get("answer", "")
    if exercise.type in {Exercise.Type.READING, Exercise.Type.LISTENING}:
        answers = {}
        for index, _question in enumerate(content.get("questions", [])):
            answers[str(index)] = request.POST.get(f"q_{index}", "")
        return answers
    return request.POST.get("answer", "")


@login_required
def progress(request):
    if request.user.is_student:
        submissions = Submission.objects.filter(student=request.user).select_related("assignment").order_by("-updated_at")
        attendance = (
            Attendance.objects.filter(student=request.user, kind=Attendance.Kind.CLASS)
            .select_related("group")
            .order_by("-lesson_date")[:20]
        )
        stats = student_stats(request.user)
        scores = [
            {"label": item.assignment.title, "value": item.score}
            for item in submissions.filter(score__isnull=False).order_by("graded_at", "updated_at")
        ]
        return render(
            request,
            "progress/index.html",
            {
                "average": stats["average"],
                "attendance": stats["attendance"],
                "progress": stats["progress"],
                "submissions": submissions,
                "attendance_rows": attendance,
                "scores": scores,
                "mix": {
                    "graded": submissions.filter(status=Submission.Status.GRADED).count(),
                    "submitted": submissions.filter(status=Submission.Status.SUBMITTED).count(),
                    "returned": submissions.filter(status=Submission.Status.RETURNED).count(),
                    "missing": stats["progress"]["pending"],
                },
            },
        )
    _require_roles(request.user, "admin", "teacher")
    rows = []
    for student in scoped_students(request.user).prefetch_related("enrollments__group"):
        stats = student_stats(student)
        rows.append(
            {
                "student": student,
                **stats,
                "groups": student.enrollments.select_related("group", "group__language"),
            }
        )
    rows.sort(key=lambda row: (not row["risk"], row["student"].last_name, row["student"].first_name))
    return render(request, "progress/roster.html", {"rows": rows, "class_charts": _class_charts(rows)})


@login_required
def student_analytics(request, pk):
    _require_roles(request.user, "admin", "teacher")
    student = get_object_or_404(scoped_students(request.user), pk=pk)
    submissions = Submission.objects.filter(student=student).select_related("assignment", "assignment__group").order_by("-updated_at")
    attendance_rows = (
        Attendance.objects.filter(student=student, kind=Attendance.Kind.CLASS)
        .select_related("group")
        .order_by("-lesson_date")[:24]
    )
    stats = student_stats(student)
    scores = [
        {"label": item.assignment.title, "value": item.score}
        for item in submissions.filter(score__isnull=False).order_by("graded_at", "updated_at")
    ]
    graded = submissions.filter(status=Submission.Status.GRADED).count()
    reviewing = submissions.filter(status=Submission.Status.SUBMITTED).count()
    returned = submissions.filter(status=Submission.Status.RETURNED).count()
    mix = {
        "graded": graded,
        "submitted": reviewing,
        "returned": returned,
        "missing": max(stats["progress"]["total"] - graded - reviewing - returned, 0),
    }
    attendance_chart = [
        {
            "label": row.lesson_date.strftime("%d.%m"),
            "value": 100 if row.status == Attendance.Status.PRESENT else 0,
        }
        for row in reversed(list(attendance_rows))
    ]
    return render(
        request,
        "progress/analytics.html",
        {
            "student": student,
            "average": stats["average"],
            "attendance": stats["attendance"],
            "progress": stats["progress"],
            "stats": stats,
            "submissions": submissions,
            "attendance_rows": attendance_rows,
            "groups": student.enrollments.select_related("group", "group__language"),
            "scores": scores,
            "mix": mix,
            "attendance_chart": attendance_chart,
        },
    )


@login_required
def audit_log(request):
    _require_primary_admin(request.user)
    logs = AuditLog.objects.select_related("actor")
    scope = request.GET.get("scope") or "staff"
    if scope != "all":
        logs = logs.filter(actor__role=User.Role.ADMIN, actor__is_primary_admin=False)
    return render(request, "audit/list.html", {"logs": logs[:300], "scope": scope})


@login_required
def telegram_settings(request):
    _require_roles(request.user, "admin")
    from django.conf import settings as django_settings

    return render(
        request,
        "settings/telegram.html",
        {
            "configured": bool(django_settings.TELEGRAM_BOT_TOKEN),
            "username": django_settings.TELEGRAM_BOT_USERNAME,
            "linked": User.objects.exclude(telegram_id=None).count(),
        },
    )


@login_required
def onboarding(request):
    if not request.user.needs_onboarding():
        return redirect("web:dashboard")
    form = OnboardingForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, "Анкета сохранена. Можно пользоваться кабинетом.")
        return redirect("web:dashboard")
    return render(request, "auth/onboarding.html", {"form": form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль сохранён.")
        return redirect("web:profile")
    link = None
    if request.GET.get("new_code") or not request.user.telegram_id:
        link = issue_link_code(request.user)
    notifications = Notification.objects.filter(user=request.user)[:20]
    return render(request, "profile/index.html", {"form": form, "link": link, "notifications": notifications})
