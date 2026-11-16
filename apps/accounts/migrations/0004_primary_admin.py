from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_assistant_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_primary_admin",
            field=models.BooleanField(default=False, verbose_name="Главный администратор"),
        ),
    ]
