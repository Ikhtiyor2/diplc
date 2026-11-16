from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.allowed_roles and request.user.role not in self.allowed_roles and not request.user.is_admin:
            raise PermissionDenied("Недостаточно прав для этого раздела.")
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin",)


class StaffRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin", "teacher")


class StudentRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("student",)
