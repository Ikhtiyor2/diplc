from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_primary_admin"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="ui_language",
            field=models.CharField(
                choices=[("ru", "Русский"), ("uz", "Oʻzbekcha")],
                default="ru",
                max_length=8,
                verbose_name="Язык интерфейса",
            ),
        ),
    ]
