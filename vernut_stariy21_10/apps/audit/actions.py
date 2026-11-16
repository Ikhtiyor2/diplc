import re

SENSITIVE = {"password", "password2", "new_password", "new_password2", "csrfmiddlewaretoken", "old_password"}

RULES = (
    (r"^/login/?$", "POST", "Вошёл в систему"),
    (r"^/logout/?$", "POST", "Вышел из системы"),
    (r"^/app/admins/create/?$", "POST", "Создал администратора"),
    (r"^/app/teachers/create/?$", "POST", "Создал преподавателя"),
    (r"^/app/lectors/create/?$", "POST", "Создал лектора"),
    (r"^/app/assistants/create/?$", "POST", "Создал ассистента"),
    (r"^/app/students/create/?$", "POST", "Создал ученика"),
    (r"^/app/groups/create/?$", "POST", "Создал группу"),
    (r"^/app/groups/\d+/edit/?$", "POST", "Изменил группу"),
    (r"^/app/groups/\d+/attendance/?$", "POST", "Отметил посещаемость"),
    (r"^/app/attendance/lecture/?$", "POST", "Отметил посещаемость лекции"),
    (r"^/app/lectures/create/?$", "POST", "Создал поток лекций"),
    (r"^/app/lectures/\d+/edit/?$", "POST", "Изменил поток лекций"),
    (r"^/app/lectures/\d+/sessions/create/?$", "POST", "Добавил лекцию в расписание"),
    (r"^/app/lectures/sessions/\d+/edit/?$", "POST", "Изменил лекцию"),
    (r"^/app/users/\d+/edit/?$", "POST", "Изменил пользователя"),
    (r"^/app/users/\d+/?$", "POST", "Обновил карточку пользователя"),
    (r"^/app/homework/create/?$", "POST", "Загрузил домашнее задание"),
    (r"^/app/homework/\d+/edit/?$", "POST", "Изменил домашнее задание"),
    (r"^/app/homework/\d+/submit/?$", "POST", "Сдал домашнее задание"),
    (r"^/app/submissions/\d+/review/?$", "POST", "Проверил домашнее задание"),
    (r"^/app/profile/?$", "POST", "Обновил профиль"),
    (r"^/app/onboarding/?$", "POST", "Заполнил анкету"),
    (r"^/app/telegram/?$", "POST", "Изменил настройки Telegram"),
)


def describe_action(method: str, path: str) -> str:
    for pattern, expected, label in RULES:
        if method == expected and re.match(pattern, path):
            return label
    leaf = path.strip("/").split("/")[0] if path else "root"
    return f"{method} {leaf or 'root'}"


def safe_post_snapshot(data) -> dict:
    snapshot = {}
    keys = data.keys() if hasattr(data, "keys") else []
    for key in keys:
        if not key or key.lower() in SENSITIVE or "password" in key.lower() or "token" in key.lower():
            continue
        value = data.get(key) if hasattr(data, "get") else None
        text = str(value or "").strip()
        if text:
            snapshot[key] = text[:120]
        if len(snapshot) >= 8:
            break
    return snapshot
