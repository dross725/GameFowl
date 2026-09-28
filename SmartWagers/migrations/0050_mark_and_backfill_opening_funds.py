from collections import defaultdict

from django.db import migrations, models


def backfill_opening_funds(apps, schema_editor):
    Event = apps.get_model('SmartWagers', 'Event')
    Settings = apps.get_model('SmartWagers', 'Settings')
    TellerTransaction = apps.get_model('SmartWagers', 'TellerTransaction')
    ArchivedTellerTransaction = apps.get_model(
        'SmartWagers', 'ArchivedTellerTransaction',
    )

    current_settings = Settings.objects.order_by('-id').first()

    for event in Event.objects.order_by('started_at', 'pk').iterator():
        active_qs = TellerTransaction.objects.filter(
            transaction_type='COLLECT',
            affects_admin_fund=False,
            cancelled=False,
            created_at__gte=event.started_at,
        )
        if event.ended_at is not None:
            # Rollover settlement rows are deliberately stamped exactly at
            # ended_at; opening funds occur before that boundary.
            active_qs = active_qs.filter(created_at__lt=event.ended_at)

        candidates = [
            {
                'source': 'active',
                'pk': row['pk'],
                'user_id': row['user_id'],
                'amount': round(float(row['amount']), 2),
                'created_at': row['created_at'],
            }
            for row in active_qs.values(
                'pk', 'user_id', 'amount', 'created_at',
            )
        ]
        archived_qs = ArchivedTellerTransaction.objects.filter(
            event_id=event.pk,
            transaction_type='COLLECT',
            affects_admin_fund=False,
            cancelled=False,
        )
        if event.ended_at is not None:
            archived_qs = archived_qs.filter(created_at__lt=event.ended_at)
        candidates.extend({
            'source': 'archived',
            'pk': row['pk'],
            'user_id': row['user_id'],
            'amount': round(float(row['amount']), 2),
            'created_at': row['created_at'],
        } for row in archived_qs.values(
            'pk', 'user_id', 'amount', 'created_at',
        ))

        if not candidates:
            if event.is_active and current_settings is not None:
                Event.objects.filter(pk=event.pk).update(
                    teller_opening_fund=round(
                        float(current_settings.teller_initial_fund), 2,
                    ),
                )
            continue

        grouped = defaultdict(list)
        for candidate in candidates:
            if candidate['amount'] > 0:
                grouped[candidate['amount']].append(candidate)
        if not grouped:
            continue

        # Opening floats normally repeat across tellers. Prefer the amount
        # issued to the most distinct tellers, then the amount seen earliest
        # in the event so end-of-event settlement COLLECTs lose ties.
        selected_amount, selected_rows = min(
            grouped.items(),
            key=lambda item: (
                -len({row['user_id'] for row in item[1]}),
                min(row['created_at'] for row in item[1]),
            ),
        )
        Event.objects.filter(pk=event.pk).update(
            teller_opening_fund=selected_amount,
        )

        # Mark at most one opening row per teller. This avoids classifying an
        # equal-valued end-of-event settlement as another opening fund.
        earliest_by_user = {}
        for row in selected_rows:
            previous = earliest_by_user.get(row['user_id'])
            if previous is None or row['created_at'] < previous['created_at']:
                earliest_by_user[row['user_id']] = row

        active_ids = [
            row['pk'] for row in earliest_by_user.values()
            if row['source'] == 'active'
        ]
        archived_ids = [
            row['pk'] for row in earliest_by_user.values()
            if row['source'] == 'archived'
        ]
        if active_ids:
            TellerTransaction.objects.filter(pk__in=active_ids).update(
                is_opening_fund=True,
            )
        if archived_ids:
            ArchivedTellerTransaction.objects.filter(pk__in=archived_ids).update(
                is_opening_fund=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('SmartWagers', '0049_event_teller_opening_fund'),
    ]

    operations = [
        migrations.AddField(
            model_name='tellertransaction',
            name='is_opening_fund',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='archivedtellertransaction',
            name='is_opening_fund',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            backfill_opening_funds,
            migrations.RunPython.noop,
        ),
    ]
