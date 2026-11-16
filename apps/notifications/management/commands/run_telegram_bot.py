from django.core.management.base import BaseCommand
from django.conf import settings
import httpx
import time

from apps.notifications.telegram import _t, process_telegram_update


class Command(BaseCommand):
    help = "Long-polling Telegram бота DiplomacyLC"

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stderr.write("TELEGRAM_BOT_TOKEN is not set.")
            while True:
                time.sleep(3600)
            return
        offset = None
        self.stdout.write("Telegram bot started.")
        try:
            for language_code in ("", "uz"):
                commands = [
                    {"command": "menu", "description": _t(language_code or "ru", "Меню")},
                    {"command": "homework", "description": _t(language_code or "ru", "Сдать домашку")},
                    {"command": "cancel", "description": _t(language_code or "ru", "Отменить выбор задания")},
                ]
                body = {"commands": commands}
                if language_code:
                    body["language_code"] = language_code
                httpx.post(
                    f"https://api.telegram.org/bot{token}/setMyCommands",
                    json=body,
                    timeout=8.0,
                )
        except httpx.HTTPError:
            pass
        while True:
            try:
                params = {"timeout": 25}
                if offset:
                    params["offset"] = offset
                response = httpx.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params=params,
                    timeout=35.0,
                )
                data = response.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    process_telegram_update(update)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(str(exc))
                time.sleep(3)
