"""
Migration 0023: Restore unique constraints on Wagers.transactionid and
TellerTransaction.transaction_id.

A data-migration step runs first to deduplicate any rows that share the
same ID (a legacy of migration 0022 which removed the constraints).
Duplicates are disambiguated by appending a numeric suffix, preserving the
original ID on the oldest (lowest-pk) row.
"""

from django.db import migrations, models


def deduplicate_wager_ids(apps, schema_editor):
    Wagers = apps.get_model('SmartWagers', 'Wagers')

    seen = {}
    for wager in Wagers.objects.order_by('id'):
        tid = wager.transactionid
        if tid in seen:
            counter = seen[tid] + 1
            seen[tid] = counter
            # Append suffix to make it unique; keep within max_length=10
            new_id = f"{tid[:7]}D{counter:02d}"
            wager.transactionid = new_id
            wager.save(update_fields=['transactionid'])
        else:
            seen[tid] = 0


def deduplicate_teller_ids(apps, schema_editor):
    TellerTransaction = apps.get_model('SmartWagers', 'TellerTransaction')

    seen = {}
    for txn in TellerTransaction.objects.order_by('id'):
        tid = txn.transaction_id
        if tid in seen:
            counter = seen[tid] + 1
            seen[tid] = counter
            new_id = f"{tid[:8]}D{counter:02d}"
            txn.transaction_id = new_id
            txn.save(update_fields=['transaction_id'])
        else:
            seen[tid] = 0


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0022_remove_unique_transaction_ids'),
    ]

    operations = [
        # 1. Deduplicate existing data before adding the constraint.
        migrations.RunPython(
            deduplicate_wager_ids,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            deduplicate_teller_ids,
            reverse_code=migrations.RunPython.noop,
        ),

        # 2. Re-add unique constraints.
        migrations.AlterField(
            model_name='wagers',
            name='transactionid',
            field=models.CharField(default='000000', editable=False, max_length=10, unique=True),
        ),
        migrations.AlterField(
            model_name='tellertransaction',
            name='transaction_id',
            field=models.CharField(default='R000000', editable=False, max_length=12, unique=True),
        ),
    ]
