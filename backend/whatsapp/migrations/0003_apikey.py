from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0002_automationsettings"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApiKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                (
                    "key_type",
                    models.CharField(
                        choices=[("send_message", "Send a WhatsApp message")],
                        default="send_message",
                        max_length=32,
                    ),
                ),
                ("key_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("prefix", models.CharField(max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "API key",
                "ordering": ["-created_at"],
            },
        ),
    ]
