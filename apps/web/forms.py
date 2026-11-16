import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.db.models import Case, IntegerField, Value, When

from apps.accounts.login_guard import clear_login_failures, login_blocked, record_login_failure
from apps.accounts.models import User
from apps.assessments.models import Question, Test
from apps.attendance.models import LectureSession, LectureStream
from apps.core.lectures import lecture_leader_queryset
from apps.groups.models import Group, Language
from apps.homework.models import Assignment
from apps.practice.models import Exercise

LOGIN_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class GroupByTeacherSelect(forms.Select):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher_map = {}

    def set_teacher_map(self, groups):
        self.teacher_map = {group.pk: group.teacher_id for group in groups}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        pk = getattr(value, "value", value)
        try:
            teacher_id = self.teacher_map.get(int(pk)) if pk not in (None, "") else None
        except (TypeError, ValueError):
            teacher_id = None
        if teacher_id:
            option["attrs"]["data-teacher"] = str(teacher_id)
        return option


class GroupByTeacherCheckboxSelect(forms.CheckboxSelectMultiple):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher_map = {}

    def set_teacher_map(self, groups):
        self.teacher_map = {group.pk: group.teacher_id for group in groups}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        pk = getattr(value, "value", value)
        try:
            teacher_id = self.teacher_map.get(int(pk)) if pk not in (None, "") else None
        except (TypeError, ValueError):
            teacher_id = None
        if teacher_id:
            option["attrs"]["data-teacher"] = str(teacher_id)
        return option


def _clean_login(login: str, instance=None, *, preserve_case: bool = False) -> str:
    value = (login or "").strip()
    if not preserve_case:
        value = value.lower()
    if not value:
        raise forms.ValidationError("Укажите логин.")
    if not LOGIN_RE.match(value):
        raise forms.ValidationError("Только латиница, цифры, точка, дефис и подчёркивание.")
    qs = User.objects.filter(login__iexact=value)
    if instance and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    if qs.exists():
        raise forms.ValidationError("Такой логин уже занят.")
    return value


def group_label(group: Group) -> str:
    teacher = group.teacher.full_name if group.teacher else "без преподавателя"
    return f"{group.name} · {group.language} · {teacher}"


def lecture_stream_group_label(group: Group) -> str:
    from apps.web.i18n import translate

    label = group_label(group)
    if not group.is_active:
        return f"{label} · {translate('неактивна')}"
    return label


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Логин",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}),
    )
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "current-password"}),
    )
    error_messages = {
        "invalid_login": "Неверный логин или пароль.",
        "inactive": "Неверный логин или пароль.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["placeholder"] = "Логин"
        self.fields["password"].widget.attrs["placeholder"] = "Пароль"

    def clean(self):
        username = (self.data.get("username") or "").strip()
        if login_blocked(self.request, username):
            raise forms.ValidationError("Слишком много попыток входа. Подождите 15 минут.")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            record_login_failure(self.request, username)
            raise
        if self.get_user() is not None:
            clear_login_failures(self.request, username)
        return cleaned


class TeacherCreateForm(forms.ModelForm):
    login = forms.CharField(
        label="Логин",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off", "placeholder": "t.sokolova"}),
        help_text="Латиница, цифры, точка. Это логин для входа преподавателя.",
    )
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["last_name", "first_name", "middle_name", "phone", "notes"]
        widgets = {
            "last_name": forms.TextInput(attrs={"class": "input"}),
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "middle_name": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["last_name"].required = True
        self.fields["first_name"].required = True
        self.order_fields(["last_name", "first_name", "middle_name", "login", "password", "password2", "phone", "notes"])

    def clean_login(self):
        return _clean_login(self.cleaned_data.get("login"))

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password") or ""
        if password != (cleaned.get("password2") or ""):
            self.add_error("password2", "Пароли не совпадают.")
        elif password:
            validate_password(password)
        return cleaned


class LectorCreateForm(TeacherCreateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["login"].widget.attrs["placeholder"] = "l.ivanov"
        self.fields["login"].help_text = "Логин лектора. Ему назначают потоки лекций — группы и расписание задаёт администратор."


class AssistantCreateForm(TeacherCreateForm):
    lead_teacher = forms.ModelChoiceField(
        label="Преподаватель",
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
        help_text="Ассистент видит только группы этого преподавателя и не может проверять чужих учеников.",
    )

    class Meta(TeacherCreateForm.Meta):
        fields = ["last_name", "first_name", "middle_name", "phone", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["login"].widget.attrs["placeholder"] = "a.krylova"
        self.fields["login"].help_text = "Логин ассистента. Доступ только к группам выбранного преподавателя."
        self.fields["lead_teacher"].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        self.order_fields(["last_name", "first_name", "middle_name", "lead_teacher", "login", "password", "password2", "phone", "notes"])


class AdminCreateForm(TeacherCreateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["login"].widget.attrs["placeholder"] = "admin2"
        self.fields["login"].help_text = "Логин второстепенного администратора. Регистр сохраняется. Главный увидит все его действия."

    def clean_login(self):
        return _clean_login(self.cleaned_data.get("login"), preserve_case=True)


class StudentCreateForm(forms.ModelForm):
    login = forms.CharField(
        label="Логин",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off", "placeholder": "s.ivanov"}),
        help_text="Латиница, цифры, точка. Передайте ученику вместе с паролем.",
    )
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )
    teacher = forms.ModelChoiceField(
        label="Преподаватель",
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "input", "id": "id_teacher"}),
        help_text="Ученик попадёт к этому преподавателю.",
    )
    group = forms.ModelChoiceField(
        label="Группа",
        queryset=Group.objects.none(),
        widget=GroupByTeacherSelect(attrs={"class": "input", "id": "id_group"}),
        help_text="Язык берётся из группы. Список групп зависит от преподавателя.",
    )

    class Meta:
        model = User
        fields = ["last_name", "first_name", "middle_name", "phone", "notes"]
        widgets = {
            "last_name": forms.TextInput(attrs={"class": "input", "placeholder": "можно оставить пустым — ученик укажет при входе"}),
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "middle_name": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["last_name"].required = False
        self.fields["first_name"].required = False
        self.fields["teacher"].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        groups = Group.objects.filter(is_active=True).select_related("language", "teacher")
        self.fields["group"].queryset = groups
        self.fields["group"].label_from_instance = group_label
        self.fields["group"].widget.set_teacher_map(groups)
        self.order_fields(
            ["last_name", "first_name", "middle_name", "login", "password", "password2", "teacher", "group", "phone", "notes"]
        )

    def clean_login(self):
        return _clean_login(self.cleaned_data.get("login"))

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password") or ""
        if password != (cleaned.get("password2") or ""):
            self.add_error("password2", "Пароли не совпадают.")
        elif password:
            validate_password(password)
        teacher = cleaned.get("teacher")
        group = cleaned.get("group")
        if teacher and group and group.teacher_id != teacher.pk:
            self.add_error("group", "Эта группа принадлежит другому преподавателю.")
        if group and not group.teacher_id:
            self.add_error("group", "У группы нет преподавателя — сначала назначьте его в карточке группы.")
        return cleaned


class UserCreateForm(StudentCreateForm):
    """Совместимость: создание ученика с логином, паролем и группой."""


class UserEditForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        label="Группы и преподаватели",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Отметьте группы — ученик будет заниматься у преподавателей этих групп.",
    )
    new_password = forms.CharField(
        label="Новый пароль",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password", "placeholder": "Оставьте пустым, если не меняете"}),
    )
    new_password2 = forms.CharField(
        label="Повторите пароль",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["last_name", "first_name", "middle_name", "login", "phone", "faculty", "course", "notes", "is_active", "role", "lead_teacher"]
        widgets = {
            "last_name": forms.TextInput(attrs={"class": "input"}),
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "middle_name": forms.TextInput(attrs={"class": "input"}),
            "login": forms.TextInput(attrs={"class": "input", "autocomplete": "off"}),
            "phone": forms.TextInput(attrs={"class": "input"}),
            "faculty": forms.TextInput(attrs={"class": "input"}),
            "course": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "role": forms.Select(attrs={"class": "input"}),
            "lead_teacher": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        groups = Group.objects.filter(is_active=True).select_related("language", "teacher")
        self.fields["groups"].queryset = groups
        self.fields["groups"].label_from_instance = group_label
        if self.instance.pk and self.instance.is_student:
            self.fields["groups"].initial = list(Group.objects.filter(enrollments__student=self.instance))
        else:
            self.fields.pop("groups")
        if self.instance.pk and self.instance.is_teacher:
            self.fields.pop("faculty")
            self.fields.pop("course")
        if "lead_teacher" in self.fields:
            self.fields["lead_teacher"].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
            self.fields["lead_teacher"].required = False
            if not (self.instance.pk and self.instance.is_assistant):
                self.fields.pop("lead_teacher")
        if not (editor and editor.is_primary_admin):
            self.fields.pop("role", None)
        elif self.instance.pk and self.instance.is_primary_admin:
            self.fields.pop("role", None)
        order = ["last_name", "first_name", "middle_name", "login", "role", "lead_teacher", "groups", "faculty", "course", "phone", "new_password", "new_password2", "notes", "is_active"]
        self.order_fields([name for name in order if name in self.fields])

    def clean_login(self):
        return _clean_login(self.cleaned_data.get("login"), instance=self.instance)

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("new_password") or ""
        confirm = cleaned.get("new_password2") or ""
        if password or confirm:
            if password != confirm:
                self.add_error("new_password2", "Пароли не совпадают.")
            elif password:
                validate_password(password, self.instance)
        return cleaned


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "language", "teacher", "level", "schedule", "room", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "language": forms.Select(attrs={"class": "input"}),
            "teacher": forms.Select(attrs={"class": "input"}),
            "level": forms.Select(attrs={"class": "input"}),
            "schedule": forms.TextInput(attrs={"class": "input", "placeholder": "Вт / Чт 18:00"}),
            "room": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teacher"].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        self.fields["teacher"].required = True
        self.fields["teacher"].empty_label = "Выберите преподавателя"
        self.fields["teacher"].help_text = "Ученики этой группы будут закреплены за этим преподавателем."
        self.fields["language"].queryset = Language.objects.all()


def _lecture_stream_groups_queryset(preferred_teacher_id=None):
    qs = Group.objects.select_related("language", "teacher")
    if preferred_teacher_id:
        qs = qs.annotate(
            sort_pref=Case(
                When(teacher_id=preferred_teacher_id, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("sort_pref", "-is_active", "name")
    else:
        qs = qs.order_by("-is_active", "name")
    return qs


class LectureStreamForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        label="Группы потока",
        queryset=Group.objects.none(),
        widget=GroupByTeacherCheckboxSelect,
        help_text="Сначала выберите ведущего. По умолчанию видны только его группы; при необходимости включите показ всех групп центра.",
    )

    class Meta:
        model = LectureStream
        fields = ["name", "lector", "schedule", "room", "is_active", "groups"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "placeholder": "МЭО · лекция · понедельник"}),
            "lector": forms.Select(attrs={"class": "input"}),
            "schedule": forms.TextInput(attrs={"class": "input", "placeholder": "Вт / Чт 18:00"}),
            "room": forms.TextInput(attrs={"class": "input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lector"].queryset = lecture_leader_queryset()
        self.fields["lector"].required = True
        self.fields["lector"].label = "Ведущий лекции"
        self.fields["lector"].empty_label = "Выберите преподавателя или лектора"
        self.fields["lector"].help_text = "Преподаватель может вести и свои группы, и назначенные потоки лекций."
        preferred_teacher_id = self._preferred_lector_id()
        groups_qs = _lecture_stream_groups_queryset(preferred_teacher_id)
        groups = list(groups_qs)
        widget = GroupByTeacherCheckboxSelect()
        widget.set_teacher_map(groups)
        self.fields["groups"].widget = widget
        self.fields["groups"].queryset = groups_qs
        self.fields["groups"].label_from_instance = lecture_stream_group_label

    def _preferred_lector_id(self):
        raw = (self.data.get("lector") if self.is_bound else None) or getattr(self.instance, "lector_id", None)
        if not raw:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None


class LectureSessionForm(forms.ModelForm):
    class Meta:
        model = LectureSession
        fields = ["date", "topic", "is_cancelled"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "topic": forms.TextInput(attrs={"class": "input", "placeholder": "Тема лекции"}),
        }


class AssignmentForm(forms.ModelForm):
    deadline = forms.DateTimeField(
        label="Дедлайн",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"],
        widget=forms.DateTimeInput(attrs={"class": "input", "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    groups = forms.ModelMultipleChoiceField(
        label="Группы",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Отметьте группы, которым уйдёт это задание. Можно выбрать несколько или все сразу.",
    )

    class Meta:
        model = Assignment
        fields = ["title", "description", "deadline", "group", "is_published"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "Worksheet 12 · Present Perfect"}),
            "description": forms.Textarea(
                attrs={
                    "class": "input",
                    "rows": 4,
                    "placeholder": "Что сделать: распечатать файл, выполнить упражнения, загрузить фото или PDF с ответами.",
                }
            ),
            "group": forms.Select(attrs={"class": "input"}),
        }

    def __init__(self, *args, group_queryset=None, multi_groups=False, initial_groups=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = group_queryset if group_queryset is not None else Group.objects.none()
        self.multi_groups = multi_groups or not self.instance.pk
        if self.multi_groups:
            self.fields.pop("group", None)
            self.fields["groups"].queryset = qs
            self.fields["groups"].required = True
            self.fields["groups"].label_from_instance = group_label
            if initial_groups:
                self.fields["groups"].initial = initial_groups
        else:
            self.fields.pop("groups", None)
            self.fields["group"].queryset = qs
            self.fields["group"].label_from_instance = group_label


class TestForm(forms.ModelForm):
    class Meta:
        model = Test
        fields = ["title", "description", "kind", "instructions", "group", "time_limit_minutes", "available_until", "is_published"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "group": forms.Select(attrs={"class": "input", "id": "test-group"}),
            "kind": forms.Select(attrs={"class": "input", "id": "test-kind"}),
            "instructions": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Инструкция на языке экзамена"}),
            "time_limit_minutes": forms.NumberInput(attrs={"class": "input", "placeholder": "60"}),
            "available_until": forms.DateTimeInput(attrs={"class": "input", "type": "datetime-local"}),
        }


class ExerciseForm(forms.ModelForm):
    content_json = forms.CharField(widget=forms.Textarea(attrs={"class": "input mono", "rows": 10}), required=False)

    class Meta:
        model = Exercise
        fields = ["title", "language", "type", "prompt", "audio", "level", "is_published"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input"}),
            "language": forms.Select(attrs={"class": "input"}),
            "type": forms.Select(attrs={"class": "input"}),
            "prompt": forms.Textarea(attrs={"class": "input", "rows": 4}),
            "level": forms.TextInput(attrs={"class": "input"}),
        }


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["last_name", "first_name", "middle_name", "phone", "avatar"]
        widgets = {
            "last_name": forms.TextInput(attrs={"class": "input"}),
            "first_name": forms.TextInput(attrs={"class": "input"}),
            "middle_name": forms.TextInput(attrs={"class": "input"}),
            "phone": forms.TextInput(attrs={"class": "input"}),
            "avatar": forms.ClearableFileInput(attrs={"class": "input", "accept": "image/*"}),
        }


def _plain_name(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _phone_digits(value: str) -> str:
    return "".join(ch for ch in value or "" if ch.isdigit())


def _phones_match(stored: str, given: str) -> bool:
    left = _phone_digits(stored)
    right = _phone_digits(given)
    if not left:
        return True
    if len(left) >= 9 and len(right) >= 9:
        return left[-9:] == right[-9:]
    return bool(right) and left == right


class PasswordResetForm(forms.Form):
    login = forms.CharField(
        label="Логин",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}),
    )
    last_name = forms.CharField(label="Фамилия", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "family-name"}))
    first_name = forms.CharField(label="Имя", widget=forms.TextInput(attrs={"class": "input", "autocomplete": "given-name"}))
    phone = forms.CharField(
        label="Телефон",
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "tel", "placeholder": "Как в профиле, если указан"}),
    )
    new_password = forms.CharField(
        label="Новый пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )
    new_password2 = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None

    def clean(self):
        cleaned = super().clean()
        login = (cleaned.get("login") or "").strip()
        if self.request is not None and login_blocked(self.request, login):
            raise forms.ValidationError("Слишком много попыток. Подождите 15 минут.")
        password = cleaned.get("new_password") or ""
        if password != (cleaned.get("new_password2") or ""):
            self.add_error("new_password2", "Пароли не совпадают.")
        user = User.objects.filter(login__iexact=login, is_active=True).first()
        matched = (
            user is not None
            and not user.is_primary_admin
            and _plain_name(user.last_name) == _plain_name(cleaned.get("last_name") or "")
            and _plain_name(user.first_name) == _plain_name(cleaned.get("first_name") or "")
            and _phones_match(user.phone, cleaned.get("phone") or "")
        )
        if not matched:
            if self.request is not None:
                record_login_failure(self.request, login)
            raise forms.ValidationError("Проверьте логин, фамилию, имя и телефон.")
        if password and not self.errors:
            validate_password(password, user)
        self.user = user
        return cleaned

    def save(self):
        user = self.user
        user.set_password(self.cleaned_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        if self.request is not None:
            clear_login_failures(self.request, user.login)
        return user


class OnboardingForm(forms.Form):
    last_name = forms.CharField(label="Фамилия", widget=forms.TextInput(attrs={"class": "input"}))
    first_name = forms.CharField(label="Имя", widget=forms.TextInput(attrs={"class": "input"}))
    middle_name = forms.CharField(label="Отчество", required=False, widget=forms.TextInput(attrs={"class": "input"}))
    faculty = forms.CharField(
        label="Факультет",
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Филологический"}),
    )
    course = forms.ChoiceField(
        label="Курс",
        required=False,
        choices=[("", "—")] + [(str(n), f"{n} курс") for n in range(1, 7)],
        widget=forms.Select(attrs={"class": "input"}),
    )
    password = forms.CharField(
        label="Новый пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "autocomplete": "new-password"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user:
            self.fields["last_name"].initial = user.last_name
            self.fields["first_name"].initial = user.first_name
            self.fields["middle_name"].initial = user.middle_name
            self.fields["faculty"].initial = user.faculty
            self.fields["course"].initial = user.course
            if user.is_student:
                self.fields["faculty"].required = True
                self.fields["course"].required = True
            else:
                self.fields.pop("faculty")
                self.fields.pop("course")

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password") or ""
        if password != (cleaned.get("password2") or ""):
            self.add_error("password2", "Пароли не совпадают.")
        elif password:
            validate_password(password, self.user)
        return cleaned

    def save(self):
        user = self.user
        user.last_name = self.cleaned_data["last_name"].strip()
        user.first_name = self.cleaned_data["first_name"].strip()
        user.middle_name = (self.cleaned_data.get("middle_name") or "").strip()
        if user.is_student:
            user.faculty = (self.cleaned_data.get("faculty") or "").strip()
            user.course = self.cleaned_data.get("course") or ""
        user.set_password(self.cleaned_data["password"])
        user.must_change_password = False
        user.profile_completed = True
        user.save()
        return user


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ["type", "question_text", "points", "order"]
        widgets = {
            "type": forms.Select(attrs={"class": "input"}),
            "question_text": forms.Textarea(attrs={"class": "input", "rows": 3}),
            "points": forms.NumberInput(attrs={"class": "input"}),
            "order": forms.NumberInput(attrs={"class": "input"}),
        }


def translate_form_fields(form):
    from apps.web.i18n import translate

    for field in form.fields.values():
        if field.label:
            field.label = translate(str(field.label))
        if field.help_text:
            field.help_text = translate(str(field.help_text))
        placeholder = field.widget.attrs.get("placeholder")
        if placeholder:
            field.widget.attrs["placeholder"] = translate(str(placeholder))
        if getattr(field, "empty_label", None):
            field.empty_label = translate(str(field.empty_label))


def _patch_form(cls):
    original = cls.__init__

    def wrapped(self, *args, **kwargs):
        original(self, *args, **kwargs)
        translate_form_fields(self)

    cls.__init__ = wrapped


for _form in (
    LoginForm,
    TeacherCreateForm,
    LectorCreateForm,
    AssistantCreateForm,
    AdminCreateForm,
    StudentCreateForm,
    UserEditForm,
    GroupForm,
    LectureStreamForm,
    LectureSessionForm,
    AssignmentForm,
    TestForm,
    ExerciseForm,
    ProfileForm,
    PasswordResetForm,
    OnboardingForm,
    QuestionForm,
):
    _patch_form(_form)
