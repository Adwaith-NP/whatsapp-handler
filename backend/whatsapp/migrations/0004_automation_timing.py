from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0003_apikey"),
    ]

    operations = [
        migrations.AddField(
            model_name="automationsettings",
            name="read_receipt_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="automationsettings",
            name="read_receipt_delay",
            field=models.PositiveSmallIntegerField(default=5),
        ),
        migrations.AddField(
            model_name="automationsettings",
            name="typing_delay",
            field=models.PositiveSmallIntegerField(default=3),
        ),
    ]
