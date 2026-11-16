from django.core.cache import cache

WINDOW_SECONDS = 15 * 60
MAX_PER_LOGIN = 8
MAX_PER_IP = 25


def _client_ip(request) -> str:
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or "unknown"


def _keys(request, login: str) -> tuple[str, str]:
    ip = _client_ip(request)
    ident = (login or "").strip().lower()
    return f"login-fail:ip:{ip}", f"login-fail:user:{ip}:{ident}"


def login_blocked(request, login: str) -> bool:
    ip_key, user_key = _keys(request, login)
    return cache.get(ip_key, 0) >= MAX_PER_IP or cache.get(user_key, 0) >= MAX_PER_LOGIN


def record_login_failure(request, login: str) -> None:
    ip_key, user_key = _keys(request, login)
    cache.set(ip_key, cache.get(ip_key, 0) + 1, WINDOW_SECONDS)
    cache.set(user_key, cache.get(user_key, 0) + 1, WINDOW_SECONDS)


def clear_login_failures(request, login: str) -> None:
    _ip_key, user_key = _keys(request, login)
    cache.delete(user_key)
