from __future__ import annotations

from django.db.models import Q

from apps.accounts.models import User


def lecture_leader_queryset():
    return User.objects.filter(
        Q(role=User.Role.TEACHER) | Q(role=User.Role.LECTOR),
        is_active=True,
    ).order_by("last_name", "first_name", "login")
