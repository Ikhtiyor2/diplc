from django.conf import settings
from apps.notifications.models import Notification


def ui(request):
    unread = 0
    if getattr(request, "user", None) and request.user.is_authenticated:
        unread = Notification.objects.filter(user=request.user, is_read=False, channel="in_app").count()
    return {
        "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
        "unread_notifications": unread,
        "product_name": "DiplomacyLC",
        "product_company": "DiplomacyLC",
    }
