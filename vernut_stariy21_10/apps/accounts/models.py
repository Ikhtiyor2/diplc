from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, login: str, password: str | None = None, **extra):
        if not login:
            raise ValueError("Логин обязателен")
        extra.setdefault("role", User.Role.STUDENT)
        user = self.model(login=login.strip(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, login: str, password: str | None = None, **extra):
        extra.setdefault("role", User.Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        return self.create_user(login, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        TEACHER = "teacher", "Преподаватель"
        LECTOR = "lector", "Лектор"
        ASSISTANT = "assistant", "Ассистент"
        STUDENT = "student", "Ученик"

    first_name = models.CharField("Имя", max_length=80, blank=True)
    last_name = models.CharField("Фамилия", max_length=80, blank=True)
    middle_name = models.CharField("Отчество", max_length=80, blank=True)
    login = models.CharField("Логин", max_length=64, unique=True)
    role = models.CharField("Роль", max_length=16, choices=Role.choices, default=Role.STUDENT)
    lead_teacher = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assistants",
        limit_choices_to={"role": "teacher"},
        verbose_name="Преподаватель",
        help_text="Для ассистента: к какому преподавателю прикреплён.",
    )
    telegram_id = models.BigIntegerField("Telegram ID", null=True, blank=True, unique=True)
    telegram_username = models.CharField("Telegram username", max_length=64, blank=True)
    avatar = models.ImageField("Аватар", upload_to="avatars/", blank=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    notes = models.TextField("Заметки", blank=True)
    faculty = models.CharField("Факультет", max_length=120, blank=True)
    course = models.CharField("Курс", max_length=32, blank=True)
    profile_completed = models.BooleanField("Анкета заполнена", default=True)
    is_active = models.BooleanField("Активен", default=True)
    is_staff = models.BooleanField(default=False)
    is_primary_admin = models.BooleanField("Главный администратор", default=False)
    ui_language = models.CharField(
        "Язык интерфейса",
        max_length=8,
        choices=[("ru", "Русский"), ("uz", "Oʻzbekcha")],
        default="ru",
    )
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField("Создан", default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "login"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(part for part in parts if part).strip() or self.login

    def needs_onboarding(self) -> bool:
        if self.must_change_password:
            return True
        if self.is_student and not self.profile_completed:
            return True
        return False

    @property
    def initials(self) -> str:
        first = self.first_name[:1].upper() if self.first_name else ""
        last = self.last_name[:1].upper() if self.last_name else ""
        return f"{last}{first}" or "?"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_secondary_admin(self) -> bool:
        return self.is_admin and not self.is_primary_admin

    @property
    def is_teacher(self) -> bool:
        return self.role == self.Role.TEACHER

    @property
    def is_lector(self) -> bool:
        """Отдельная учётка только для лекций (без своих групп)."""
        return self.role == self.Role.LECTOR

    @property
    def can_manage_lectures(self) -> bool:
        if self.is_lector:
            return True
        if not self.is_teacher or not self.pk:
            return False
        from apps.attendance.models import LectureStream

        return LectureStream.objects.filter(lector_id=self.pk, is_active=True).exists()

    @property
    def is_assistant(self) -> bool:
        return self.role == self.Role.ASSISTANT

    @property
    def is_teaching_staff(self) -> bool:
        return self.is_teacher or self.is_assistant or self.is_lector

    @property
    def is_student(self) -> bool:
        return self.role == self.Role.STUDENT

    @property
    def role_label(self) -> str:
        from apps.web.i18n import translate

        if self.is_primary_admin:
            return translate("Главный администратор")
        if self.is_admin:
            return translate("Администратор")
        return translate(self.get_role_display())


class TelegramLink(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="telegram_link")
    code = models.CharField(max_length=12, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Код привязки Telegram"
        verbose_name_plural = "Коды привязки Telegram"

    def __str__(self) -> str:
        return f"{self.user} / {self.code}"
