from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0047_settings_teller_bet_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="payouts_held",
            field=models.BooleanField(default=False),
        ),
    ]
