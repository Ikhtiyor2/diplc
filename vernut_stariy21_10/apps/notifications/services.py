from __future__ import annotations

from datetime import timedelta

import httpx
from django.conf import settings
from django.utils import timezone

from .models import Notification


def homework_entry_markup() -> dict:
    return {"inline_keyboard": [[{"text": "Сдать домашку", "callback_data": "hwmenu"}]]}


def send_telegram_message(telegram_id: int, text: str, reply_markup: dict | None = None) -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not telegram_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": telegram_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = httpx.post(url, json=payload, timeout=8.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def answer_telegram_callback(callback_id: str, text: str = "") -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not callback_id:
        return False
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        response = httpx.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=8.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _localize(user, text: str, **parts) -> str:
    from django.utils import translation

    from apps.web.i18n import normalize_lang, translate

    with translation.override(normalize_lang(getattr(user, "ui_language", None))):
        rendered = translate(text)
        if parts:
            try:
                rendered = rendered.format(**parts)
            except (KeyError, IndexError, ValueError):
                pass
        return rendered


def _localize_markup(user, markup: dict | None) -> dict | None:
    if not markup:
        return None
    key = "inline_keyboard" if "inline_keyboard" in markup else "keyboard" if "keyboard" in markup else ""
    if not key:
        return markup
    rows = []
    for row in markup[key]:
        updated = []
        for button in row:
            item = dict(button)
            if item.get("text"):
                item["text"] = _localize(user, item["text"])
            updated.append(item)
        rows.append(updated)
    localized = dict(markup)
    localized[key] = rows
    return localized


def notify_user(user, title: str, body: str, payload: dict | None = None, reply_markup: dict | None = None, **parts) -> Notification:
    title = _localize(user, title)
    body = _localize(user, body, **parts)
    reply_markup = _localize_markup(user, reply_markup)
    notification = Notification.objects.create(
        user=user,
        title=title,
        body=body,
        channel=Notification.Channel.IN_APP,
        payload=payload or {},
    )
    if user.telegram_id:
        sent = send_telegram_message(user.telegram_id, f"<b>{title}</b>\n{body}", reply_markup=reply_markup)
        if sent:
            Notification.objects.create(
                user=user,
                title=title,
                body=body,
                channel=Notification.Channel.TELEGRAM,
                payload=payload or {},
                sent_at=timezone.now(),
            )
    return notification


def _group_students(group):
    return [item.student for item in group.enrollments.select_related("student")]


def notify_homework_published(assignment) -> None:
    for student in _group_students(assignment.group):
        if assignment.deadline:
            notify_user(
                student,
                "Новое домашнее задание",
                "«{work}» для группы {group}. Дедлайн: {deadline}.",
                {"assignment_id": assignment.id},
                reply_markup=homework_entry_markup(),
                work=assignment.title,
                group=assignment.group.name,
                deadline=assignment.deadline.strftime("%d.%m.%Y %H:%M"),
            )
        else:
            notify_user(
                student,
                "Новое домашнее задание",
                "«{work}» для группы {group}. Дедлайн: без срока.",
                {"assignment_id": assignment.id},
                reply_markup=homework_entry_markup(),
                work=assignment.title,
                group=assignment.group.name,
            )


def notify_test_published(test) -> None:
    for student in _group_students(test.group):
        notify_user(
            student,
            "Новый тест",
            "«{work}» доступен в группе {group}.",
            {"test_id": test.id},
            work=test.title,
            group=test.group.name,
        )


def notify_submission_received(submission) -> None:
    teacher = submission.assignment.group.teacher
    if teacher:
        notify_user(
            teacher,
            "Новая сдача задания",
            "{name} отправил(а) «{work}».",
            {"submission_id": submission.id},
            name=submission.student.full_name,
            work=submission.assignment.title,
            reply_markup={"inline_keyboard": [[{"text": "На проверке", "callback_data": "tqueue"}]]},
        )


def notify_homework_graded(submission) -> None:
    score = submission.score if submission.score is not None else "—"
    body = "«{work}»: {score}/100.\nКомментарий: {feedback}" if submission.feedback else "«{work}»: {score}/100."
    notify_user(
        submission.student,
        "Оценка за задание",
        body,
        {"submission_id": submission.id},
        work=submission.assignment.title,
        score=score,
        feedback=submission.feedback or "",
    )


def notify_test_graded(attempt) -> None:
    notify_user(
        attempt.student,
        "Результат теста",
        "«{work}»: {score} баллов.",
        {"attempt_id": attempt.id},
        work=attempt.test.title,
        score=attempt.score if attempt.score is not None else "—",
    )


def notify_deadlines_tomorrow() -> int:
    from apps.homework.models import Assignment, Submission

    start = timezone.now()
    end = start + timedelta(hours=24)
    count = 0
    assignments = Assignment.objects.filter(is_published=True, deadline__range=(start, end))
    for assignment in assignments:
        submitted_ids = set(
            Submission.objects.filter(
                assignment=assignment,
                status__in=[Submission.Status.SUBMITTED, Submission.Status.GRADED],
            ).values_list("student_id", flat=True)
        )
        for student in _group_students(assignment.group):
            if student.id in submitted_ids:
                continue
            notify_user(
                student,
                "Дедлайн завтра",
                "Завтра истекает срок сдачи «{work}».",
                {"assignment_id": assignment.id},
                work=assignment.title,
            )
            count += 1
    return count


def notify_review_reminders() -> int:
    from apps.homework.models import Submission

    count = 0
    pending = Submission.objects.filter(status=Submission.Status.SUBMITTED).select_related(
        "assignment__group__teacher", "student", "assignment"
    )
    teachers = {}
    for submission in pending:
        teacher = submission.assignment.group.teacher
        if not teacher:
            continue
        teachers.setdefault(teacher, 0)
        teachers[teacher] += 1
    for teacher, amount in teachers.items():
        notify_user(
            teacher,
            "Напоминание о проверке",
            "У вас {amount} работ ожидают проверки.",
            {"pending": amount},
            amount=amount,
        )
        count += 1
    return count
