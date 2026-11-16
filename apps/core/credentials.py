from __future__ import annotations

import secrets
import string

from django.utils.text import slugify

RU_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def transliterate(value: str) -> str:
    text = (value or "").lower().replace("ʻ", "").replace("ʼ", "").replace("’", "").replace("`", "")
    text = text.replace("o‘", "o").replace("o'", "o").replace("g‘", "g").replace("g'", "g")
    text = text.replace("о‘", "o").replace("ғ", "g").replace("қ", "q").replace("ў", "o")
    chars = []
    for char in text:
        chars.append(RU_MAP.get(char, char))
    return slugify("".join(chars)) or "user"


def generate_login(last_name: str, first_name: str = "", role: str = "student") -> str:
    from apps.accounts.models import User

    base = transliterate(last_name) or "user"
    prefix = {"admin": "adm", "teacher": "t", "lector": "l", "assistant": "a", "student": "s"}.get(role, "u")
    initial = transliterate(first_name[:1]) if first_name else ""
    candidate = f"{prefix}.{base}{initial}"
    login = candidate
    index = 1
    while User.objects.filter(login=login).exists():
        index += 1
        login = f"{candidate}{index}"
    return login


def generate_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password):
            return password
