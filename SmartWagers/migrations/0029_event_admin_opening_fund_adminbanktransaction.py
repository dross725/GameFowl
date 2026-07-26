import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0028_settings_admin_initial_fund'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='tellertransaction',
            name='affects_admin_fund',
            field=models.BooleanField(default=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='event',
            name='admin_opening_fund',
            field=models.FloatField(default=100000.0),
        ),
        migrations.CreateModel(
            name='AdminBankTransaction',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'transaction_type',
                    models.CharField(
                        choices=[('BORROW', 'Borrow'), ('REMIT', 'Remit')],
                        max_length=10,
                    ),
                ),
                ('amount', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'admin',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='admin_bank_transactions',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'event',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='admin_bank_transactions',
                        to='SmartWagers.event',
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(
                        fields=['event', 'transaction_type'],
                        name='SmartWagers_event_i_1d6110_idx',
                    ),
                ],
                'constraints': [
                    models.CheckConstraint(
                        condition=models.Q(('amount__gt', 0)),
                        name='admin_bank_transaction_amount_positive',
                    ),
                ],
            },
        ),
        migrations.AlterField(
            model_name='tellertransaction',
            name='affects_admin_fund',
            field=models.BooleanField(default=True),
        ),
    ]
