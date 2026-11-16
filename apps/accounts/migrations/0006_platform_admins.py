from django.db import migrations


def seed_platform_admins(apps, schema_editor):
    from apps.accounts.bootstrap import ensure_platform_admins

    ensure_platform_admins()


def unseed_platform_admins(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(login__iexact="MaakCEOadmin").delete()
    User.objects.filter(login__iexact="admin1dlc").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_ui_language"),
    ]

    operations = [
        migrations.RunPython(seed_platform_admins, unseed_platform_admins),
    ]
