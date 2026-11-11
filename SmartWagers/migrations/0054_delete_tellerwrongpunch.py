from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0053_printdevice_platform_chromeos"),
    ]

    operations = [
        migrations.DeleteModel(
            name="TellerWrongPunch",
        ),
    ]
