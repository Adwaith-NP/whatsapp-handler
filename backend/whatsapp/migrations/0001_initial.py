from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="GeminiSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("api_key", models.CharField(blank=True, default="", max_length=255)),
                ("model", models.CharField(default="gemini-3.6-flash", max_length=100)),
                ("instruction", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Gemini settings",
                "verbose_name_plural": "Gemini settings",
            },
        ),
    ]
