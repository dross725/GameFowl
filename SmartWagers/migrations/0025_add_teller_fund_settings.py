from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0024_add_teller_max_balance_to_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='settings',
            name='teller_initial_fund',
            field=models.FloatField(default=10000.0),
        ),
        migrations.AddField(
            model_name='settings',
            name='teller_min_balance',
            field=models.FloatField(default=0.0),
        ),
    ]
