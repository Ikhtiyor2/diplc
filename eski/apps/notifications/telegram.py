from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import TelegramLink, User
from apps.notifications.services import notify_user


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


def handle_bot_update(payload: dict) -> str:
    message = payload.get("message") or payload.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    telegram_id = chat.get("id")
    username = chat.get("username") or ""
    if not telegram_id:
        return "ignored"
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1] if len(parts) > 1 else ""
        if code:
            user = bind_telegram(code, telegram_id, username)
            return "bound" if user else "invalid_code"
        return "hello"
    if text.startswith("/whoami"):
        user = User.objects.filter(telegram_id=telegram_id).first()
        return "linked" if user else "not_linked"
    if len(text) == 6 and text.isalnum():
        user = bind_telegram(text, telegram_id, username)
        return "bound" if user else "invalid_code"
    return "unknown"


def bot_reply(kind: str) -> str:
    username = settings.TELEGRAM_BOT_USERNAME
    replies = {
        "hello": (
            "Привет! Это бот DiplomacyLC.\n"
            "Откройте профиль на платформе, скопируйте код привязки и отправьте его сюда.\n"
            f"Или перейдите по ссылке: https://t.me/{username}"
        ),
        "bound": "Аккаунт успешно привязан. Теперь вы будете получать уведомления.",
        "invalid_code": "Код не найден или истёк. Сгенерируйте новый в профиле.",
        "linked": "Этот Telegram уже привязан к аккаунту DiplomacyLC.",
        "not_linked": "Telegram ещё не привязан. Отправьте код из профиля.",
        "unknown": "Отправьте код привязки из профиля DiplomacyLC или команду /start.",
    }
    return replies.get(kind, replies["unknown"])
