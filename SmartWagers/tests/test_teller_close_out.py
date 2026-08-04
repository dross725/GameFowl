"""Tests for teller station close-out flow."""

import pytest
from django.test import Client
from django.utils.timezone import now

from SmartWagers.models import (
    Event, TellerCloseOut, TellerStatus, TellerTransaction, Wagers,
)
from SmartWagers import services


@pytest.fixture
def teller_client(db, teller_user, teller_status_online):
    client = Client()
    client.force_login(teller_user)
    return client


@pytest.fixture
def admin_client(db, admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def event_with_fight(db, active_event, open_fight):
    return active_event


def _place_bet(teller_user, amount=500.0, fightnum=1):
    return Wagers.objects.create(
        fightnum=fightnum,
        side='MERON',
        wager=amount,
        cashier=str(teller_user),
        registered=True,
    )


@pytest.mark.django_db
class TestCloseTellerStation:
    def test_close_station_creates_snapshot(
        self, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 1500.0)
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=10000.0,
            affects_admin_fund=False,
        )

        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        assert close_out.fightnum == 1
        assert close_out.expected_cash_on_hand == 11500.0
        assert close_out.grand_total == 1500.0
        assert close_out.collect_total == 10000.0
        assert TellerStatus.objects.get(user=teller_user).is_online is False

    def test_duplicate_close_rejected(
        self, teller_user, event_with_fight, teller_status_online,
    ):
        services.close_teller_station(teller_user, event=event_with_fight)
        with pytest.raises(services.StationAlreadyClosedError):
            services.close_teller_station(teller_user, event=event_with_fight)

    def test_close_without_active_event_rejected(self, teller_user, teller_status_online):
        Event.objects.filter(is_active=True).update(is_active=False)
        with pytest.raises(services.NoActiveEventError):
            services.close_teller_station(teller_user)

    def test_teller_close_station_endpoint(
        self, teller_client, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 800.0)
        response = teller_client.post('/reports/close-station/')
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['close_out']['expected_cash_on_hand'] == 800.0
        assert TellerCloseOut.objects.filter(user=teller_user, event=event_with_fight).exists()

    def test_duplicate_close_endpoint_returns_409(
        self, teller_client, teller_user, event_with_fight, teller_status_online,
    ):
        services.close_teller_station(teller_user, event=event_with_fight)
        response = teller_client.post('/reports/close-station/')
        assert response.status_code == 409
        assert response.json()['error'] == 'already_closed'


@pytest.mark.django_db
class TestBetBlockingAfterClose:
    def test_post_user_returns_403_after_close(
        self, teller_client, teller_user, event_with_fight, open_fight, teller_status_online,
    ):
        services.close_teller_station(teller_user, event=event_with_fight)
        response = teller_client.post(
            '/user',
            {'wager_value': '100', 'wager_id': 'MERON'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        assert response.status_code == 403
        assert response.json()['error'] == 'station_closed'

    def test_reprint_returns_403_after_close(
        self, teller_client, teller_user, event_with_fight, teller_status_online,
    ):
        wager = _place_bet(teller_user)
        services.close_teller_station(teller_user, event=event_with_fight)
        response = teller_client.post(
            '/reprint_wager/',
            {'transaction_id': wager.transactionid},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        assert response.status_code == 403
        assert response.json()['error'] == 'station_closed'


@pytest.mark.django_db
class TestAdminCashCount:
    def test_register_count_creates_remit_and_variance(
        self, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 2000.0)
        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        result = services.register_teller_cash_count(close_out.pk, 1950.0, admin_user)

        assert result.actual_cash_counted == 1950.0
        assert result.variance == -50.0
        assert result.remit_transaction is not None
        assert result.remit_transaction.transaction_type == TellerTransaction.REMIT
        assert result.remit_transaction.received is True
        assert result.remit_transaction.amount == 1950.0

    def test_admin_count_endpoint(
        self, admin_client, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 1000.0)
        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        response = admin_client.post(
            '/administrator/teller-closeout/count/',
            {'close_out_id': close_out.pk, 'actual_amount': '1000'},
        )
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['variance'] == 0.0

    def test_admin_count_endpoint_accepts_comma_formatted_amount(
        self, admin_client, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 1000.0)
        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        response = admin_client.post(
            '/administrator/teller-closeout/count/',
            {'close_out_id': close_out.pk, 'actual_amount': '1,000.00'},
        )
        assert response.status_code == 200
        assert response.json()['ok'] is True
        assert response.json()['variance'] == 0.0

    def test_register_count_works_with_inflated_teller_sequence(
        self, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        from SmartWagers.models import TransactionSequence

        _place_bet(teller_user, 500.0)
        close_out = services.close_teller_station(teller_user, event=event_with_fight)
        TransactionSequence.objects.filter(key=TransactionSequence.TELLER).update(
            value=2026000047,
        )

        result = services.register_teller_cash_count(close_out.pk, 500.0, admin_user)

        assert result.actual_cash_counted == 500.0
        assert result.remit_transaction is not None
        assert int(result.remit_transaction.transaction_id[1:]) <= 999999

    def test_admin_cannot_reenable_before_count(
        self, admin_client, teller_user, event_with_fight, teller_status_online,
    ):
        services.close_teller_station(teller_user, event=event_with_fight)
        response = admin_client.post(
            '/administrator/teller-online-toggle/',
            {'teller_id': teller_user.pk, 'is_online': 'true'},
        )
        assert response.status_code == 409
        assert response.json()['error'] == 'awaiting_cash_count'


@pytest.mark.django_db
class TestEventReportCloseOut:
    def test_event_report_includes_variance(
        self, admin_client, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 3000.0)
        close_out = services.close_teller_station(teller_user, event=event_with_fight)
        services.register_teller_cash_count(close_out.pk, 3100.0, admin_user)

        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Reconciled' in content
        assert '3100' in content.replace(',', '')
