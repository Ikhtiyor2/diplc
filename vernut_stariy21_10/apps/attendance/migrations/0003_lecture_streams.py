# Generated manually for lecture streams

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0002_ru_roster"),
        ("attendance", "0002_attendancesession"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="attendance",
            name="kind",
            field=models.CharField(
                choices=[("class", "Занятие в группе"), ("lecture", "Лекция (устар.)")],
                default="class",
                max_length=16,
                verbose_name="Тип занятия",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="attendance",
            unique_together={("student", "group", "lesson_date", "kind")},
        ),
        migrations.CreateModel(
            name="LectureStream",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, verbose_name="Название потока")),
                (
                    "weekday",
                    models.IntegerField(
                        choices=[
                            (0, "Понедельник"),
                            (1, "Вторник"),
                            (2, "Среда"),
                            (3, "Четверг"),
                            (4, "Пятница"),
                            (5, "Суббота"),
                            (6, "Воскресенье"),
                        ],
                        default=0,
                        verbose_name="День недели",
                    ),
                ),
                ("start_time", models.TimeField(blank=True, null=True, verbose_name="Время начала")),
                ("room", models.CharField(blank=True, max_length=32, verbose_name="Аудитория")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "groups",
                    models.ManyToManyField(related_name="lecture_streams", to="groups.group", verbose_name="Группы"),
                ),
                (
                    "lector",
                    models.ForeignKey(
                        limit_choices_to={"role": "lector"},
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lecture_streams",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Лектор",
                    ),
                ),
            ],
            options={
                "verbose_name": "Поток лекций",
                "verbose_name_plural": "Потоки лекций",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="LectureSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(verbose_name="Дата")),
                ("topic", models.CharField(max_length=240, verbose_name="Тема")),
                ("is_cancelled", models.BooleanField(default=False, verbose_name="Отменена")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "stream",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions",
                        to="attendance.lecturestream",
                        verbose_name="Поток",
                    ),
                ),
            ],
            options={
                "verbose_name": "Лекция",
                "verbose_name_plural": "Лекции",
                "ordering": ["-date", "stream__name"],
                "unique_together": {("stream", "date")},
            },
        ),
        migrations.CreateModel(
            name="LectureAttendance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[("present", "Присутствовал"), ("absent", "Отсутствовал")],
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "marked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="marked_lecture_attendance",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_records",
                        to="attendance.lecturesession",
                        verbose_name="Лекция",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        limit_choices_to={"role": "student"},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lecture_attendance_records",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Ученик",
                    ),
                ),
            ],
            options={
                "verbose_name": "Посещаемость лекции",
                "verbose_name_plural": "Посещаемость лекций",
                "ordering": ["-session__date", "student__last_name"],
                "unique_together": {("session", "student")},
            },
        ),
    ]
