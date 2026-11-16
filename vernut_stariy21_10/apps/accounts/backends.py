from django.contrib.auth.backends import ModelBackend

from .models import User


class CaseInsensitiveLoginBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        login = username if username is not None else kwargs.get(User.USERNAME_FIELD)
        if login is None or password is None:
            return None
        user = User.objects.filter(login__iexact=str(login).strip()).first()
        if user is None:
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
