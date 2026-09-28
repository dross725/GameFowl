from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps
from django.utils.timezone import now

from SmartWagers.models import Event, TellerTransaction


@pytest.mark.django_db
def test_backfill_uses_actual_opening_fund_and_ignores_rollover_settlement(
        teller_user, default_settings):
    ended_at = now() - timedelta(hours=1)
    event = Event.objects.create(
        name='Historical Event',
        started_at=ended_at - timedelta(hours=6),
        ended_at=ended_at,
        is_active=False,
        teller_opening_fund=10000,
    )
    opening = TellerTransaction.objects.create(
        user=teller_user,
        transaction_type=TellerTransaction.COLLECT,
        amount=15000,
        affects_admin_fund=False,
    )
    settlement = TellerTransaction.objects.create(
        user=teller_user,
        transaction_type=TellerTransaction.COLLECT,
        amount=5000,
        affects_admin_fund=False,
    )
    TellerTransaction.objects.filter(pk=opening.pk).update(
        created_at=event.started_at + timedelta(minutes=1),
    )
    TellerTransaction.objects.filter(pk=settlement.pk).update(
        created_at=event.ended_at,
    )

    migration = import_module(
        'SmartWagers.migrations.0050_mark_and_backfill_opening_funds'
    )
    migration.backfill_opening_funds(apps, None)

    event.refresh_from_db()
    opening.refresh_from_db()
    settlement.refresh_from_db()
    assert event.teller_opening_fund == 15000
    assert opening.is_opening_fund is True
    assert settlement.is_opening_fund is False
