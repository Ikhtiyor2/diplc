from django.db import migrations, models


WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


def copy_weekday_time_to_schedule(apps, schema_editor):
    LectureStream = apps.get_model("attendance", "LectureStream")
    for stream in LectureStream.objects.all():
        parts = []
        try:
            parts.append(WEEKDAYS[stream.weekday])
        except (IndexError, TypeError):
            pass
        if stream.start_time:
            parts.append(stream.start_time.strftime("%H:%M"))
        stream.schedule = " · ".join(parts)
        stream.save(update_fields=["schedule"])


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0004_lecture_stream_teacher_lectors"),
    ]

    operations = [
        migrations.AddField(
            model_name="lecturestream",
            name="schedule",
            field=models.CharField(blank=True, max_length=160, verbose_name="Расписание"),
        ),
        migrations.RunPython(copy_weekday_time_to_schedule, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="lecturestream",
            name="start_time",
        ),
        migrations.RemoveField(
            model_name="lecturestream",
            name="weekday",
        ),
    ]
