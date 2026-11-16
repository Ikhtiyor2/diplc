from __future__ import annotations

from django.db.models import QuerySet


def staff_teacher_id(user) -> int | None:
    if getattr(user, "is_teacher", False):
        return user.pk
    if getattr(user, "is_assistant", False):
        return user.lead_teacher_id
    return None


def scoped_lecture_streams(user) -> QuerySet:
    from apps.attendance.models import LectureStream

    qs = LectureStream.objects.select_related("lector").prefetch_related("groups")
    if user.is_admin:
        return qs
    if getattr(user, "can_manage_lectures", False):
        return qs.filter(lector=user)
    return qs.none()


def can_access_lecture_stream(user, stream) -> bool:
    if user.is_admin:
        return True
    if getattr(user, "can_manage_lectures", False):
        return scoped_lecture_streams(user).filter(pk=getattr(stream, "pk", stream)).exists()
    return False


def _lector_group_ids(user) -> QuerySet:
    return scoped_lecture_streams(user).values_list("groups__pk", flat=True).distinct()


def scoped_groups(user) -> QuerySet:
    from apps.groups.models import Group

    qs = Group.objects.select_related("teacher", "language")
    if user.is_admin:
        return qs
    if getattr(user, "is_lector", False):
        return qs.filter(pk__in=_lector_group_ids(user))
    lead_id = staff_teacher_id(user)
    teacher_groups = qs.filter(teacher_id=lead_id) if lead_id else qs.none()
    if getattr(user, "is_teacher", False) and getattr(user, "can_manage_lectures", False):
        stream_groups = qs.filter(pk__in=_lector_group_ids(user))
        if lead_id:
            return (teacher_groups | stream_groups).distinct()
        return stream_groups
    if lead_id:
        return teacher_groups
    return qs.filter(enrollments__student=user).distinct()


def scoped_students(user) -> QuerySet:
    from apps.accounts.models import User

    qs = User.objects.filter(role=User.Role.STUDENT, is_active=True)
    if user.is_admin:
        return qs
    if getattr(user, "is_lector", False):
        return qs.filter(enrollments__group__in=scoped_groups(user)).distinct()
    lead_id = staff_teacher_id(user)
    if lead_id:
        teacher_students = qs.filter(enrollments__group__teacher_id=lead_id)
        if getattr(user, "is_teacher", False) and getattr(user, "can_manage_lectures", False):
            return (
                teacher_students | qs.filter(enrollments__group__in=_lector_group_ids(user))
            ).distinct()
        return teacher_students.distinct()
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
