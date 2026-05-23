from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0015_sessionlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="wagers",
            name="registered",
            field=models.BooleanField(default=True),
        ),
    ]
