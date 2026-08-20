from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0004_automation_timing"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatMemory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("chat_jid", models.CharField(db_index=True, max_length=64)),
                (
                    "role",
                    models.CharField(
                        choices=[("user", "Them"), ("model", "AI")], max_length=8
                    ),
                ),
                ("text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "chat memory",
                "verbose_name_plural": "chat memory",
                "ordering": ["id"],
            },
        ),
        migrations.AddIndex(
            model_name="chatmemory",
            index=models.Index(fields=["chat_jid", "id"], name="whatsapp_ch_chat_ji_37716f_idx"),
        ),
    ]
