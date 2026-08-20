from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutomationSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("reply_to_all", models.BooleanField(default=False)),
                ("skip_direct", models.BooleanField(default=False)),
                ("skip_groups", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Automation settings",
                "verbose_name_plural": "Automation settings",
            },
        ),
    ]
