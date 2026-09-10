from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("SmartWagers", "0044_tellertransaction_cancelled_edited"),
    ]

    operations = [
        migrations.AddField(
            model_name="tellercloseout",
            name="cash_count_edited",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="tellercloseout",
            name="previous_actual_cash_counted",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tellercloseout",
            name="cash_count_edited_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="edited_cash_counts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="tellercloseout",
            name="cash_count_edited_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
