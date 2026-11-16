from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class IsStaffRole(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_admin or user.is_teaching_staff))


class RolePermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        required = getattr(view, "required_roles", None)
        if not required:
            return True
        return user.role in required or user.is_admin


class IsOwnerOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_admin or user.is_teaching_staff:
            return True
        student_id = getattr(obj, "student_id", None)
        if student_id:
            return student_id == user.id
        if hasattr(obj, "login"):
            return obj.id == user.id
        return False


class ReadOnlyOrStaff(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.is_admin or user.is_teaching_staff
