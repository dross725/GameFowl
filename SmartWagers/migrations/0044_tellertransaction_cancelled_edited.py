from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0043_tellerwrongpunch"),
    ]

    operations = [
        migrations.AddField(
            model_name="archivedtellertransaction",
            name="cancelled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="archivedtellertransaction",
            name="edited",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="archivedtellertransaction",
            name="updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tellertransaction",
            name="cancelled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="tellertransaction",
            name="edited",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="tellertransaction",
            name="updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="tellertransaction",
            index=models.Index(
                fields=["cancelled", "transaction_type"],
                name="SmartWagers_cancell_cee96e_idx",
            ),
        ),
    ]
