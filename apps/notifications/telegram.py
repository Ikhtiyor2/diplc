from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone, translation

from apps.accounts.models import TelegramLink, User
from apps.homework.models import Assignment, Submission, SubmissionFile
from apps.notifications.models import TelegramHomeworkPick
from apps.notifications.services import notify_user
from apps.web.i18n import normalize_lang, translate


def _t(lang: str | None, message: str, **kwargs) -> str:
    with translation.override(normalize_lang(lang)):
        return translate(message, **kwargs)


def _lang(user=None, code: str = "") -> str:
    if user is not None and getattr(user, "ui_language", None):
        return normalize_lang(user.ui_language)
    return normalize_lang(code)


def issue_link_code(user: User) -> TelegramLink:
    TelegramLink.objects.filter(user=user).delete()
    code = secrets.token_hex(3).upper()
    return TelegramLink.objects.create(
        user=user,
        code=code,
        expires_at=timezone.now() + timedelta(hours=12),
    )


def bind_telegram(code: str, telegram_id: int, username: str = "") -> User | None:
    link = (
        TelegramLink.objects.select_related("user")
        .filter(code=code.upper().strip(), expires_at__gte=timezone.now())
        .first()
    )
    if not link:
        return None
    user = link.user
    user.telegram_id = telegram_id
    user.telegram_username = username or user.telegram_username
    user.save(update_fields=["telegram_id", "telegram_username"])
    link.delete()
    notify_user(user, "Telegram привязан", "Уведомления будут приходить в этот чат.")
    return user


@dataclass
class BotAction:
    kind: str
    chat_id: int | None = None
    text: str = ""
    markup: dict | None = None
    callback_id: str | None = None
    file_id: str = ""
    upload_name: str = ""
    caption: str = ""
    user_id: int | None = None


def _user_by_telegram(telegram_id: int) -> User | None:
    if not telegram_id:
        return None
    return User.objects.filter(telegram_id=telegram_id).first()


def _assignment_day(assignment: Assignment) -> date | None:
    if not assignment.deadline:
        return None
    value = timezone.localtime(assignment.deadline) if timezone.is_aware(assignment.deadline) else assignment.deadline
    return value.date()


def open_assignments(user: User):
    graded = Submission.objects.filter(student=user, status=Submission.Status.GRADED).values("assignment_id")
    return (
        Assignment.objects.filter(is_published=True, group__enrollments__student=user)
        .exclude(pk__in=graded)
        .select_related("group")
        .distinct()
        .order_by("deadline", "id")
    )


BUTTONS = {
    "Сдать домашку": "hwmenu",
    "Мои работы": "mystatus",
    "Сроки": "deadlines",
    "Меню": "menu",
    "На проверке": "tqueue",
    "Группы": "tgroups",
}


def _button_data(text: str) -> str | None:
    for source, data in BUTTONS.items():
        if text == source or text == _t("uz", source):
            return data
    return None


def _reply_keyboard(lang: str, rows: list[list[str]]) -> dict:
    return {
        "keyboard": [[{"text": _t(lang, label)} for label in row] for row in rows],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def _btn(lang: str, text: str, data: str) -> dict:
    return {"text": _t(lang, text), "callback_data": data}


def _menu_markup(user: User | None = None) -> dict:
    lang = _lang(user)
    if user is not None and not user.is_student and (user.is_teaching_staff or user.is_admin):
        return {
            "inline_keyboard": [
                [_btn(lang, "На проверке", "tqueue")],
                [_btn(lang, "Группы", "tgroups"), _btn(lang, "Сроки", "deadlines")],
            ]
        }
    return {
        "inline_keyboard": [
            [_btn(lang, "Сдать домашку", "hwmenu")],
            [_btn(lang, "Мои работы", "mystatus"), _btn(lang, "Сроки", "deadlines")],
        ]
    }


def _role_keyboard(user: User) -> dict | None:
    lang = _lang(user)
    if user.is_student:
        return _reply_keyboard(lang, [["Сдать домашку", "Мои работы"], ["Сроки"]])
    if user.is_teaching_staff or user.is_admin:
        return _reply_keyboard(lang, [["На проверке", "Группы"], ["Сроки"]])
    return None


def _role_hello(user: User) -> str:
    if user.is_student:
        return "student_menu"
    if user.is_teaching_staff or user.is_admin:
        return "teacher_menu"
    return "linked"


def _back_to_menu(user: User | None = None) -> dict:
    return {"inline_keyboard": [[_btn(_lang(user), "В меню", "menu")]]}


def _date_markup(user: User) -> tuple[str, dict | None]:
    buckets: dict[date | None, int] = {}
    for assignment in open_assignments(user):
        day = _assignment_day(assignment)
        buckets[day] = buckets.get(day, 0) + 1
    lang = _lang(user)
    if not buckets:
        return _t(lang, "Открытых домашних заданий нет."), _back_to_menu(user)
    rows = []
    for day in sorted(item for item in buckets if item is not None):
        rows.append(
            [
                {
                    "text": f"{day.strftime('%d.%m.%Y')} · {buckets[day]}",
                    "callback_data": f"hwd:{day.isoformat()}",
                }
            ]
        )
    if None in buckets:
        rows.append([{"text": _t(lang, "Без срока · {count}", count=buckets[None]), "callback_data": "hwd:none"}])
    rows.append([_btn(lang, "В меню", "menu")])
    return _t(lang, "Выберите дату сдачи."), {"inline_keyboard": rows}


def _assignment_markup(user: User, day: date | None) -> tuple[str, dict | None]:
    rows = []
    for assignment in open_assignments(user):
        if _assignment_day(assignment) != day:
            continue
        title = assignment.title if len(assignment.title) <= 40 else assignment.title[:37] + "…"
        rows.append([{"text": title, "callback_data": f"hw:{assignment.pk}"}])
    lang = _lang(user)
    rows.append(
        [
            _btn(lang, "К датам", "hwmenu"),
            _btn(lang, "В меню", "menu"),
        ]
    )
    if len(rows) == 1:
        label = _t(lang, "Без срока") if day is None else day.strftime("%d.%m.%Y")
        return _t(lang, "На {label} заданий нет.", label=label), {"inline_keyboard": rows}
    label = _t(lang, "без срока") if day is None else day.strftime("%d.%m.%Y")
    return _t(lang, "Задания на {label}. Выберите, что сдаёте.", label=label), {"inline_keyboard": rows}


def _status_text(user: User) -> str:
    submissions = (
        Submission.objects.filter(student=user)
        .select_related("assignment")
        .order_by("-updated_at")[:8]
    )
    lang = _lang(user)
    if not submissions:
        return _t(lang, "Сдач пока нет. Нажмите «Сдать домашку», когда будете готовы.")
    labels = {
        Submission.Status.DRAFT: "черновик",
        Submission.Status.SUBMITTED: "на проверке",
        Submission.Status.RETURNED: "на доработке",
        Submission.Status.GRADED: "проверено",
    }
    lines = [_t(lang, "Мои работы:")]
    for submission in submissions:
        status = _t(lang, labels.get(submission.status, submission.status))
        score = ""
        if submission.status == Submission.Status.GRADED and submission.score is not None:
            score = f" · {submission.score:g}/100"
        lines.append(f"• {escape(submission.assignment.title)} — {status}{score}")
    return "\n".join(lines)


def _deadlines_text(user: User) -> str:
    assignments = list(open_assignments(user)[:10])
    lang = _lang(user)
    if not assignments:
        return _t(lang, "Открытых сроков нет.")
    lines = [_t(lang, "Ближайшие сдачи:")]
    for assignment in assignments:
        day = _assignment_day(assignment)
        when = day.strftime("%d.%m") if day else _t(lang, "без срока")
        lines.append(f"• {when} — {escape(assignment.title)}")
    return "\n".join(lines)


def _teacher_groups(user: User):
    from apps.core.scoping import scoped_groups

    return scoped_groups(user).filter(is_active=True).order_by("name")


def _teacher_queue_text(user: User) -> str:
    pending = (
        Submission.objects.filter(assignment__group__in=_teacher_groups(user), status=Submission.Status.SUBMITTED)
        .select_related("student", "assignment", "assignment__group")
        .order_by("submitted_at")[:10]
    )
    lang = _lang(user)
    if not pending:
        return _t(lang, "Все работы проверены.")
    lines = [_t(lang, "Ждут проверки:")]
    for submission in pending:
        lines.append(
            f"• {escape(submission.student.full_name)} — {escape(submission.assignment.title)} ({escape(submission.assignment.group.name)})"
        )
    return "\n".join(lines)


def _teacher_groups_text(user: User) -> str:
    groups = list(_teacher_groups(user)[:12])
    lang = _lang(user)
    if not groups:
        return _t(lang, "Группы ещё не назначены.")
    lines = [_t(lang, "Группы:")]
    for group in groups:
        lines.append(_t(lang, "• {name} — {count} учеников", name=escape(group.name), count=group.enrollments.count()))
    return "\n".join(lines)


def _teacher_deadlines_text(user: User) -> str:
    now = timezone.now()
    groups = _teacher_groups(user)
    upcoming = list(
        Assignment.objects.filter(group__in=groups, is_published=True, deadline__gte=now)
        .select_related("group")
        .order_by("deadline")[:8]
    )
    if len(upcoming) < 8:
        upcoming.extend(
            Assignment.objects.filter(group__in=groups, is_published=True, deadline__isnull=True).select_related("group")[
                : 8 - len(upcoming)
            ]
        )
    lang = _lang(user)
    if not upcoming:
        return _t(lang, "Ближайших сроков нет.")
    lines = [_t(lang, "Сроки заданий:")]
    for assignment in upcoming:
        day = _assignment_day(assignment)
        when = day.strftime("%d.%m") if day else _t(lang, "без срока")
        lines.append(f"• {when} — {escape(assignment.title)} ({escape(assignment.group.name)})")
    return "\n".join(lines)


def _can_submit(user: User, assignment: Assignment) -> bool:
    if not user.is_student or not assignment.is_published:
        return False
    return assignment.group.enrollments.filter(student=user).exists()


def choose_assignment(user: User, assignment_id: int) -> str:
    assignment = Assignment.objects.filter(pk=assignment_id).first()
    if assignment is None or not _can_submit(user, assignment):
        return "unavailable"
    graded = Submission.objects.filter(
        assignment=assignment,
        student=user,
        status=Submission.Status.GRADED,
    ).exists()
    if graded:
        return "graded"
    TelegramHomeworkPick.objects.update_or_create(user=user, defaults={"assignment": assignment})
    return "chosen"


def save_homework_upload(user: User, filename: str, content: bytes, caption: str = "") -> str:
    pick = TelegramHomeworkPick.objects.select_related("assignment").filter(user=user).first()
    if pick is None:
        return "no_pick"
    assignment = pick.assignment
    if not _can_submit(user, assignment):
        pick.delete()
        return "unavailable"
    graded = Submission.objects.filter(
        assignment=assignment,
        student=user,
        status=Submission.Status.GRADED,
    ).exists()
    if graded:
        pick.delete()
        return "graded"
    submission = Submission.objects.filter(assignment=assignment, student=user).first()
    if submission is None:
        submission = Submission(assignment=assignment, student=user)
    if caption and not submission.answer:
        submission.answer = caption.strip()
    submission.status = Submission.Status.SUBMITTED
    submission.submitted_at = timezone.now()
    submission.save()
    safe_name = (filename or "file").replace("\\", "/").split("/")[-1].strip() or "file"
    SubmissionFile.objects.create(
        submission=submission,
        file=ContentFile(content, name=safe_name[:180]),
        original_name=safe_name[:255],
    )
    return "saved"


def _linked_user(telegram_id: int) -> User | None:
    return _user_by_telegram(telegram_id)


def prepare_update(payload: dict) -> BotAction:
    callback = payload.get("callback_query") or {}
    if callback:
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        sender = callback.get("from") or {}
        telegram_id = sender.get("id") or chat_id
        incoming = _lang(code=sender.get("language_code") or "")
        action = BotAction(kind="unknown", chat_id=chat_id, callback_id=callback.get("id") or "")
        user = _linked_user(telegram_id)
        if user is None:
            action.kind = "not_linked"
            action.text = bot_reply("not_linked", incoming)
            return action
        action.user_id = user.pk
        data = (callback.get("data") or "").strip()
        return _callback_action(action, user, data)

    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    sender = message.get("from") or {}
    telegram_id = sender.get("id") or chat_id
    incoming = _lang(code=sender.get("language_code") or "")
    text = (message.get("text") or "").strip()
    action = BotAction(kind="ignored", chat_id=chat_id, caption=(message.get("caption") or "").strip())
    if not telegram_id:
        return action

    document = message.get("document") or {}
    photos = message.get("photo") or []
    if document.get("file_id") or photos:
        user = _linked_user(telegram_id)
        if user is None:
            action.kind = "not_linked"
            action.text = bot_reply("not_linked", incoming)
            return action
        action.user_id = user.pk
        if document.get("file_id"):
            action.file_id = document["file_id"]
            action.upload_name = document.get("file_name") or "file"
        else:
            action.file_id = photos[-1]["file_id"]
            action.upload_name = "photo.jpg"
        action.kind = "upload"
        return action

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1] if len(parts) > 1 else ""
        if code:
            user = bind_telegram(code, telegram_id, chat.get("username") or "")
            action.kind = "bound" if user else "invalid_code"
        else:
            user = _linked_user(telegram_id)
            action.kind = "hello_linked" if user else "hello"
        reply_user = _linked_user(telegram_id) if action.kind in {"bound", "hello_linked"} else None
        action.text = bot_reply(action.kind, _lang(reply_user, sender.get("language_code") or ""))
        if reply_user and _role_keyboard(reply_user):
            action.text = bot_reply(_role_hello(reply_user), _lang(reply_user))
            action.markup = _role_keyboard(reply_user)
        return action

    pressed = _button_data(text)
    if text.startswith("/menu") or pressed:
        user = _linked_user(telegram_id)
        if user is None:
            action.kind = "not_linked"
            action.text = bot_reply("not_linked", incoming)
            return action
        if text.startswith("/menu") or pressed == "menu":
            return _callback_action(action, user, "menu")
        return _callback_action(action, user, pressed)

    if text.startswith("/homework"):
        user = _linked_user(telegram_id)
        if user is None:
            action.kind = "not_linked"
            action.text = bot_reply("not_linked", incoming)
            return action
        return _callback_action(action, user, "hwmenu")

    if text.startswith("/cancel"):
        user = _linked_user(telegram_id)
        if user is None:
            action.kind = "not_linked"
            action.text = bot_reply("not_linked", incoming)
            return action
        TelegramHomeworkPick.objects.filter(user=user).delete()
        action.kind = "cancelled"
        action.text = _t(_lang(user), "Выбор задания сброшен.")
        action.markup = _role_keyboard(user)
        return action

    if text.startswith("/whoami"):
        user = _linked_user(telegram_id)
        action.kind = "linked" if user else "not_linked"
        action.text = bot_reply(_role_hello(user) if user else action.kind, _lang(user, sender.get("language_code") or ""))
        if user:
            action.markup = _role_keyboard(user)
        return action

    if len(text) == 6 and text.isalnum():
        user = bind_telegram(text, telegram_id, chat.get("username") or "")
        action.kind = "bound" if user else "invalid_code"
        action.text = bot_reply(_role_hello(user) if user else action.kind, _lang(user, sender.get("language_code") or ""))
        if user:
            action.markup = _role_keyboard(user)
        return action

    if text:
        action.kind = "unknown"
        action.text = bot_reply("unknown", incoming)
    return action


def _callback_action(action: BotAction, user: User, data: str) -> BotAction:
    if data == "menu":
        action.kind = "menu"
        action.text = bot_reply(_role_hello(user), _lang(user))
        action.markup = _menu_markup(user)
        return action
    if not user.is_student:
        return _teacher_callback(action, user, data)
    if data == "mystatus":
        action.kind = "mystatus"
        action.text = _status_text(user)
        action.markup = _back_to_menu(user)
        return action
    if data == "deadlines":
        action.kind = "deadlines"
        action.text = _deadlines_text(user)
        action.markup = _back_to_menu(user)
        return action
    if data == "hwmenu":
        text, markup = _date_markup(user)
        action.kind = "homework_dates"
        action.text = text
        action.markup = markup
        return action
    if data.startswith("hwd:"):
        raw = data.split(":", 1)[1]
        day = None
        if raw != "none":
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                action.kind = "unknown"
                action.text = bot_reply("unknown", _lang(user))
                return action
        text, markup = _assignment_markup(user, day)
        action.kind = "homework_day"
        action.text = text
        action.markup = markup
        return action
    if data.startswith("hw:"):
        raw = data.split(":", 1)[1]
        if not raw.isdigit():
            action.kind = "unknown"
            action.text = bot_reply("unknown", _lang(user))
            return action
        result = choose_assignment(user, int(raw))
        assignment = Assignment.objects.filter(pk=int(raw)).first()
        title = escape(assignment.title) if assignment else _t(_lang(user), "задание")
        if result == "chosen":
            action.kind = "await_file"
            action.text = _t(
                _lang(user),
                "«{title}»\nПришлите фото или файл. Можно несколько сообщений — всё попадёт в эту сдачу.\nОтмена: /cancel",
                title=title,
            )
            return action
        if result == "graded":
            action.kind = "graded"
            action.text = _t(_lang(user), "«{title}» уже проверено. Новую работу по нему отправить нельзя.", title=title)
            return action
        action.kind = "unavailable"
        action.text = _t(_lang(user), "Это задание больше нельзя сдать.")
        return action
    action.kind = "unknown"
    action.text = bot_reply("unknown", _lang(user))
    return action


def _teacher_callback(action: BotAction, user: User, data: str) -> BotAction:
    if not (user.is_teaching_staff or user.is_admin):
        action.kind = "students_only"
        action.text = _t(_lang(user), "Этот раздел доступен ученикам и преподавателям.")
        return action
    if data == "tqueue":
        action.kind = "tqueue"
        action.text = _teacher_queue_text(user)
        action.markup = _back_to_menu(user)
        return action
    if data == "tgroups":
        action.kind = "tgroups"
        action.text = _teacher_groups_text(user)
        action.markup = _back_to_menu(user)
        return action
    if data == "deadlines":
        action.kind = "deadlines"
        action.text = _teacher_deadlines_text(user)
        action.markup = _back_to_menu(user)
        return action
    action.kind = "students_only"
    action.text = _t(_lang(user), "Сдавать домашку в боте могут ученики. Откройте «На проверке», «Группы» или «Сроки».")
    action.markup = _menu_markup(user)
    return action


def finish_upload(action: BotAction, filename: str, content: bytes) -> BotAction:
    user = User.objects.filter(pk=action.user_id).first()
    if user is None:
        action.kind = "not_linked"
        action.text = bot_reply("not_linked")
        return action
    if not user.is_student:
        action.kind = "students_only"
        action.text = _t(_lang(user), "Сдавать домашку в боте могут ученики.")
        return action
    result = save_homework_upload(user, filename or action.upload_name, content, action.caption)
    pick = TelegramHomeworkPick.objects.select_related("assignment").filter(user=user).first()
    title = escape(pick.assignment.title) if pick else _t(_lang(user), "задание")
    if result == "saved":
        action.kind = "saved"
        action.text = _t(_lang(user), "Файл принят. «{title}» на проверке у преподавателя. Можно прислать ещё файл.", title=title)
        return action
    if result == "no_pick":
        action.kind = "no_pick"
        action.text = _t(_lang(user), "Сначала откройте «Сдать домашку» и выберите задание.")
        action.markup = _menu_markup()
        return action
    if result == "graded":
        action.kind = "graded"
        action.text = _t(_lang(user), "Эта работа уже проверена.")
        return action
    action.kind = "unavailable"
    action.text = _t(_lang(user), "Это задание больше нельзя сдать.")
    return action


def bot_reply(kind: str, lang: str = "ru") -> str:
    username = settings.TELEGRAM_BOT_USERNAME
    replies = {
        "hello": (
            "Привет! Это бот DiplomacyLC.\n"
            "Откройте профиль на платформе, скопируйте код привязки и отправьте его сюда.\n"
            "Или перейдите по ссылке: https://t.me/{username}"
        ),
        "hello_linked": "Аккаунт уже привязан.",
        "student_menu": "Меню ученика.\nСдать домашку — выбрать дату и прислать файл.\nМои работы — статус сдач.\nСроки — что ещё не закрыто.",
        "teacher_menu": "Меню преподавателя.\nНа проверке — кто сдал работу.\nГруппы — ваши группы.\nСроки — ближайшие дедлайны.",
        "bound": "Аккаунт успешно привязан.",
        "invalid_code": "Код не найден или истёк. Сгенерируйте новый в профиле.",
        "linked": "Этот Telegram уже привязан к аккаунту DiplomacyLC.",
        "not_linked": "Telegram ещё не привязан. Отправьте код из профиля.",
        "unknown": "Откройте /menu или нажмите кнопку внизу: сдать домашку, мои работы, сроки.",
    }
    return _t(lang, replies.get(kind, replies["unknown"]), username=username)


def handle_bot_update(payload: dict) -> str:
    return prepare_update(payload).kind


def process_telegram_update(payload: dict, download=None) -> str:
    from apps.notifications.services import answer_telegram_callback, send_telegram_message

    action = prepare_update(payload)
    if action.kind == "upload" and action.file_id:
        loader = download or _download_telegram_file
        try:
            filename, content = loader(action.file_id)
        except Exception:
            action.kind = "file_failed"
            owner = User.objects.filter(pk=action.user_id).first() if action.user_id else None
            action.text = _t(_lang(owner), "Не получилось скачать файл. Пришлите его ещё раз.")
        else:
            action = finish_upload(action, filename or action.upload_name, content)
    if action.callback_id:
        answer_telegram_callback(action.callback_id)
    if action.chat_id and action.text:
        send_telegram_message(action.chat_id, action.text, reply_markup=action.markup)
    return action.kind


def _download_telegram_file(file_id: str) -> tuple[str, bytes]:
    import httpx

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    meta = httpx.get(
        f"https://api.telegram.org/bot{token}/getFile",
        params={"file_id": file_id},
        timeout=15.0,
    )
    meta.raise_for_status()
    path = meta.json()["result"]["file_path"]
    response = httpx.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=30.0)
    response.raise_for_status()
    name = path.replace("\\", "/").split("/")[-1] or "file"
    return name, response.content
