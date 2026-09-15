from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0046_print_device_print_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="settings",
            name="teller_bet_limit",
            field=models.FloatField(default=0.0),
        ),
    ]
