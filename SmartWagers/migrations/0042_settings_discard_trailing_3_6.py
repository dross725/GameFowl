from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0041_enforce_rollover_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="settings",
            name="discard_trailing_3_6",
            field=models.BooleanField(default=True),
        ),
    ]
