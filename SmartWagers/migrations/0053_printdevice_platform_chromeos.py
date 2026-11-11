from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0052_advance_borrow_fightnum"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printdevice",
            name="platform",
            field=models.CharField(
                choices=[
                    ("android", "Android"),
                    ("ios", "iOS"),
                    ("chromeos", "Chrome OS"),
                ],
                max_length=16,
            ),
        ),
    ]
