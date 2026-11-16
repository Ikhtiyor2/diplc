import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0005_lecturestream_schedule"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LectureCheckInSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("lesson_date", models.DateField(verbose_name="Дата лекции")),
                ("token", models.CharField(max_length=16, unique=True, verbose_name="Код")),
                ("is_open", models.BooleanField(default=True, verbose_name="Сбор открыт")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="opened_lecture_checkins",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "stream",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checkin_sessions",
                        to="attendance.lecturestream",
                        verbose_name="Поток",
                    ),
                ),
            ],
            options={
                "verbose_name": "Сбор посещаемости лекции",
                "verbose_name_plural": "Сборы посещаемости лекций",
                "ordering": ["-created_at"],
            },
        ),
    ]
