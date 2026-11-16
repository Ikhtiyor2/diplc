from django.apps import AppConfig


class HomeworkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.homework"
    label = "homework"
    verbose_name = "Домашние задания"

    def ready(self):
        from . import signals  # noqa: F401
