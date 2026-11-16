from __future__ import annotations

from datetime import timedelta

import httpx
from django.conf import settings
from django.utils import timezone

from .models import Notification


def send_telegram_message(telegram_id: int, text: str) -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not telegram_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": telegram_id, "text": text, "parse_mode": "HTML"},
            timeout=8.0,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def notify_user(user, title: str, body: str, payload: dict | None = None) -> Notification:
    notification = Notification.objects.create(
        user=user,
        title=title,
        body=body,
        channel=Notification.Channel.IN_APP,
        payload=payload or {},
    )
    if user.telegram_id:
        sent = send_telegram_message(user.telegram_id, f"<b>{title}</b>\n{body}")
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
        deadline = assignment.deadline.strftime("%d.%m.%Y %H:%M") if assignment.deadline else "без срока"
        notify_user(
            student,
            "Новое домашнее задание",
            f"«{assignment.title}» для группы {assignment.group.name}. Дедлайн: {deadline}.",
            {"assignment_id": assignment.id},
        )


def notify_test_published(test) -> None:
    for student in _group_students(test.group):
        notify_user(
            student,
            "Новый тест",
            f"«{test.title}» доступен в группе {test.group.name}.",
            {"test_id": test.id},
        )


def notify_submission_received(submission) -> None:
    teacher = submission.assignment.group.teacher
    if teacher:
        notify_user(
            teacher,
            "Новая сдача задания",
            f"{submission.student.full_name} отправил(а) «{submission.assignment.title}».",
            {"submission_id": submission.id},
        )


def notify_homework_graded(submission) -> None:
    score = submission.score if submission.score is not None else "—"
    extra = f"\nКомментарий: {submission.feedback}" if submission.feedback else ""
    notify_user(
        submission.student,
        "Оценка за задание",
        f"«{submission.assignment.title}»: {score}/100.{extra}",
        {"submission_id": submission.id},
    )


def notify_test_graded(attempt) -> None:
    notify_user(
        attempt.student,
        "Результат теста",
        f"«{attempt.test.title}»: {attempt.score if attempt.score is not None else '—'} баллов.",
        {"attempt_id": attempt.id},
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
                f"Завтра истекает срок сдачи «{assignment.title}».",
                {"assignment_id": assignment.id},
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
            f"У вас {amount} работ ожидают проверки.",
            {"pending": amount},
        )
        count += 1
    return count
