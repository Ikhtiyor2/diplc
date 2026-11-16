import os

from .models import User

PRIMARY_ADMIN_LOGIN = os.getenv("DIPLC_PRIMARY_ADMIN_LOGIN", "MaakCEOadmin")
PRIMARY_ADMIN_PASSWORD = os.getenv("DIPLC_PRIMARY_ADMIN_PASSWORD", "Maak1CEO321$")
SECONDARY_ADMIN_LOGIN = os.getenv("DIPLC_SECONDARY_ADMIN_LOGIN", "admin1dlc")
SECONDARY_ADMIN_PASSWORD = os.getenv("DIPLC_SECONDARY_ADMIN_PASSWORD", "Admin1DLC321$")


def _upsert_admin(*, login: str, password: str, primary: bool, first_name: str, last_name: str) -> User:
    user = User.objects.filter(login__iexact=login).first()
    if user is None:
        user = User(login=login)
    user.login = login
    user.role = User.Role.ADMIN
    user.is_primary_admin = primary
    user.is_staff = primary
    user.is_superuser = primary
    user.is_active = True
    user.must_change_password = False
    user.profile_completed = True
    if not user.first_name:
        user.first_name = first_name
    if not user.last_name:
        user.last_name = last_name
    user.set_password(password)
    user.save()
    return user


def ensure_platform_admins() -> tuple[User, User]:
    User.objects.filter(login__iexact="admin").exclude(login__iexact=PRIMARY_ADMIN_LOGIN).delete()
    primary = _upsert_admin(
        login=PRIMARY_ADMIN_LOGIN,
        password=PRIMARY_ADMIN_PASSWORD,
        primary=True,
        first_name="Главный",
        last_name="Администратор",
    )
    secondary = _upsert_admin(
        login=SECONDARY_ADMIN_LOGIN,
        password=SECONDARY_ADMIN_PASSWORD,
        primary=False,
        first_name="Второй",
        last_name="Администратор",
    )
    User.objects.filter(role=User.Role.ADMIN, is_primary_admin=True).exclude(pk=primary.pk).update(
        is_primary_admin=False, is_superuser=False, is_staff=False
    )
    return primary, secondary
