from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0048_event_payouts_held'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='teller_opening_fund',
            field=models.FloatField(default=10000.0),
        ),
    ]
