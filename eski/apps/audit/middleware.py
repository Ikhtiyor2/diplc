from django.utils.deprecation import MiddlewareMixin

from .actions import describe_action, safe_post_snapshot
from .models import AuditLog

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PREFIXES = ("/static/", "/media/", "/api/schema/", "/api/docs/")


class AuditMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if request.method not in MUTATING:
            return response
        path = request.path
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return response
        if path.startswith("/admin/jsi18n/") or "/review/lock/" in path:
            return response
        user = getattr(request, "user", None)
        actor = user if getattr(user, "is_authenticated", False) else None
        metadata = {"status": response.status_code}
        if request.method == "POST":
            snapshot = safe_post_snapshot(getattr(request, "POST", {}))
            if snapshot:
                metadata["fields"] = snapshot
        try:
            AuditLog.objects.create(
                actor=actor,
                action=describe_action(request.method, path)[:160],
                method=request.method,
                path=path[:255],
                metadata=metadata,
                ip_address=_client_ip(request),
            )
        except Exception:
            pass
        return response


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
