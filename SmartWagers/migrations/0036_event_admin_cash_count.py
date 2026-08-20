from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("SmartWagers", "0035_wagers_client_request_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="actual_admin_cash_counted",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="admin_cash_counted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="admin_cash_counted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="admin_cash_counts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="admin_cash_variance",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="expected_admin_cash_on_hand",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
