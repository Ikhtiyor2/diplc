from django.apps import apps as django_apps


def get_user_model():
    return django_apps.get_model("accounts", "User")
