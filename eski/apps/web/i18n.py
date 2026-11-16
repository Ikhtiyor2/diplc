from __future__ import annotations

from django.utils.functional import lazy
from django.utils.translation import get_language

from .locale_uz import STRINGS as UZ_STRINGS

UI_LANGUAGES = (("ru", "Русский"), ("uz", "Oʻzbekcha"))
DEFAULT_LANGUAGE = "ru"


def normalize_lang(code: str | None) -> str:
    value = (code or DEFAULT_LANGUAGE).lower().replace("_", "-")
    if value.startswith("uz"):
        return "uz"
    return "ru"


def current_language() -> str:
    return normalize_lang(get_language())


def translate(message, **kwargs) -> str:
    if message is None:
        return ""
    text = str(message)
    if not text:
        return text
    if current_language() == "uz":
        text = UZ_STRINGS.get(text, text)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


_ = translate
gettext_lazy = lazy(translate, str)
