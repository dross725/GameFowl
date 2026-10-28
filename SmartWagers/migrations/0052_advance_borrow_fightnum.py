from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0051_eventreportemail"),
    ]

    operations = [
        migrations.AddField(
            model_name="tellertransaction",
            name="fightnum",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="adminbanktransaction",
            name="fightnum",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="archivedtellertransaction",
            name="fightnum",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="archivedadminbanktransaction",
            name="fightnum",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
