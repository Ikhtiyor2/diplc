from django.core.management.base import BaseCommand
from django.conf import settings
import httpx
import time

from apps.notifications.telegram import bot_reply, handle_bot_update


class Command(BaseCommand):
    help = "Long-polling Telegram бота DiplomacyLC"

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stderr.write("TELEGRAM_BOT_TOKEN не задан — бот ждёт конфигурацию.")
            while True:
                time.sleep(3600)
            return
        offset = None
        self.stdout.write("Telegram-бот запущен.")
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
                    kind = handle_bot_update(update)
                    message = update.get("message") or {}
                    chat_id = (message.get("chat") or {}).get("id")
                    if chat_id and kind not in {"ignored"}:
                        httpx.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": bot_reply(kind)},
                            timeout=8.0,
                        )
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(str(exc))
                time.sleep(3)
