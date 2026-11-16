from django.core.management.base import BaseCommand

from apps.notifications.services import notify_deadlines_tomorrow, notify_review_reminders


class Command(BaseCommand):
    help = "Отправляет напоминания о дедлайнах и проверке работ"

    def handle(self, *args, **options):
        deadlines = notify_deadlines_tomorrow()
        reviews = notify_review_reminders()
        self.stdout.write(f"Дедлайны: {deadlines}, напоминания преподавателям: {reviews}")
