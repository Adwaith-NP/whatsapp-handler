from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0005_chatmemory"),
    ]

    operations = [
        migrations.AddField(
            model_name="automationsettings",
            name="batch_window",
            field=models.PositiveSmallIntegerField(default=6),
        ),
    ]
