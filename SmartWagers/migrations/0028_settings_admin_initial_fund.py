from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0027_wagers_cancelled'),
    ]

    operations = [
        migrations.AddField(
            model_name='settings',
            name='admin_initial_fund',
            field=models.FloatField(default=100000.0),
        ),
    ]
