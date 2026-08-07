from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0034_tellercloseout"),
    ]

    operations = [
        migrations.AddField(
            model_name="wagers",
            name="client_request_id",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text="Client-generated UUID for idempotent bet submission.",
                max_length=36,
                null=True,
                unique=True,
            ),
        ),
    ]
