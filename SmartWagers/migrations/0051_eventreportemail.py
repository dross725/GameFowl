from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0050_mark_and_backfill_opening_funds'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventReportEmail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recipients', models.JSONField(default=list)),
                ('missing_superusers', models.JSONField(default=list)),
                ('payload', models.JSONField(default=dict)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('sending', 'Sending'),
                        ('sent', 'Sent'),
                        ('failed', 'Failed'),
                        ('no_recipients', 'No recipients'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=20,
                )),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('event', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='commission_report_email',
                    to='SmartWagers.event',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
