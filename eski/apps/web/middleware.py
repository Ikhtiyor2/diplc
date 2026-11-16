from django.conf import settings
from django.utils import translation

from apps.web.i18n import DEFAULT_LANGUAGE, normalize_lang


class UILanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            lang = getattr(user, "ui_language", None)
        if not lang:
            lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        lang = normalize_lang(lang or DEFAULT_LANGUAGE)
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        response.setdefault("Content-Language", lang)
        translation.deactivate()
        return response
