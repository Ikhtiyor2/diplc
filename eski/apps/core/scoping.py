from __future__ import annotations

from django.db.models import QuerySet


def staff_teacher_id(user) -> int | None:
    if getattr(user, "is_teacher", False):
        return user.pk
    if getattr(user, "is_assistant", False):
        return user.lead_teacher_id
    return None


def scoped_groups(user) -> QuerySet:
    from apps.groups.models import Group

    qs = Group.objects.select_related("teacher", "language")
    if user.is_admin or getattr(user, "is_lector", False):
        return qs
    lead_id = staff_teacher_id(user)
    if lead_id:
        return qs.filter(teacher_id=lead_id)
    return qs.filter(enrollments__student=user).distinct()


def scoped_students(user) -> QuerySet:
    from apps.accounts.models import User

    qs = User.objects.filter(role=User.Role.STUDENT, is_active=True)
    if user.is_admin or getattr(user, "is_lector", False):
        return qs
    lead_id = staff_teacher_id(user)
    if lead_id:
        return qs.filter(enrollments__group__teacher_id=lead_id).distinct()
    return qs.filter(pk=user.pk)


def can_access_group(user, group) -> bool:
    if user.is_admin:
        return True
    return scoped_groups(user).filter(pk=getattr(group, "pk", group)).exists()


def student_groups(user):
    from apps.groups.models import Group

    if user.is_student:
        return Group.objects.filter(enrollments__student=user).select_related("teacher", "language")
    return scoped_groups(user)
