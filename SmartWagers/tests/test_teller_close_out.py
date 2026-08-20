"""Tests for teller station close-out flow."""

from html.parser import HTMLParser

import pytest
from django.test import Client
from django.utils.timezone import now

from SmartWagers.models import (
    AdminBankTransaction, Event, Fight_Results, TellerCloseOut, TellerStatus,
    TellerTransaction, Wagers,
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


class _TableWidthParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.table_id = None
        self.in_row = False
        self.current_width = 0
        self.widths = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'table':
            self.table_id = attributes.get('id')
            if self.table_id:
                self.widths.setdefault(self.table_id, [])
        elif tag == 'tr' and self.table_id:
            self.in_row = True
            self.current_width = 0
        elif tag in {'th', 'td'} and self.in_row:
            self.current_width += int(attributes.get('colspan', '1'))

    def handle_endtag(self, tag):
        if tag == 'tr' and self.in_row:
            self.widths[self.table_id].append(self.current_width)
            self.in_row = False
        elif tag == 'table':
            self.table_id = None


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

    def test_register_count_recovers_from_inflated_teller_sequence(
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
        assert result.remit_transaction.transaction_id == 'R000000'

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
class TestAdminReopenStation:
    def test_reopen_deletes_close_out_and_sets_teller_online(
        self, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        reopened_teller = services.reopen_teller_station(close_out.pk, admin_user)

        assert reopened_teller == teller_user
        assert not TellerCloseOut.objects.filter(pk=close_out.pk).exists()
        assert TellerStatus.objects.get(user=teller_user).is_online is True
        assert services.teller_station_is_closed(teller_user, event_with_fight) is False

    def test_admin_reopen_endpoint_allows_betting_again(
        self, admin_client, teller_client, teller_user, event_with_fight,
        open_fight, teller_status_online,
    ):
        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        response = admin_client.post(
            '/administrator/teller-closeout/reopen/',
            {'close_out_id': close_out.pk},
        )

        assert response.status_code == 200
        assert response.json() == {
            'ok': True,
            'teller_id': teller_user.pk,
            'is_online': True,
        }
        bet_response = teller_client.post(
            '/user',
            {'wager_value': '100', 'wager_id': 'MERON'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        assert bet_response.status_code == 200

    def test_reconciled_close_out_cannot_be_reopened(
        self, admin_client, admin_user, teller_user, event_with_fight,
        teller_status_online,
    ):
        close_out = services.close_teller_station(teller_user, event=event_with_fight)
        services.register_teller_cash_count(close_out.pk, 0, admin_user)

        response = admin_client.post(
            '/administrator/teller-closeout/reopen/',
            {'close_out_id': close_out.pk},
        )

        assert response.status_code == 409
        assert response.json()['error'] == 'already_counted'
        assert TellerCloseOut.objects.filter(pk=close_out.pk).exists()
        assert TellerStatus.objects.get(user=teller_user).is_online is False

    def test_reopen_endpoint_requires_admin(
        self, teller_client, teller_user, event_with_fight, teller_status_online,
    ):
        close_out = services.close_teller_station(teller_user, event=event_with_fight)

        response = teller_client.post(
            '/administrator/teller-closeout/reopen/',
            {'close_out_id': close_out.pk},
        )

        assert response.status_code == 403
        assert TellerCloseOut.objects.filter(pk=close_out.pk).exists()


@pytest.mark.django_db
class TestEventReportCloseOut:
    def test_event_report_includes_unpaid_cancelled_fight_refunds(
        self, admin_client, admin_user, teller_user, event_with_fight,
    ):
        first_refund = _place_bet(teller_user, 500.0)
        second_refund = Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=700.0,
            cashier=str(teller_user),
            registered=True,
        )
        admin_refund = Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=400.0,
            cashier=str(admin_user),
            registered=True,
        )
        Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=300.0,
            cashier=str(teller_user),
            registered=True,
            cashed_out=True,
        )
        Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=200.0,
            cashier=str(teller_user),
            registered=True,
            cancelled=True,
        )
        Fight_Results.objects.create(
            fightnum=1,
            side='CANCELLED',
            totalpot=2100.0,
            odds='REFUND',
            event=event_with_fight,
        )
        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )

        outstanding = response.context['unclaimed_detail_list']
        assert {row['transactionid'] for row in outstanding} == {
            first_refund.transactionid,
            second_refund.transactionid,
            admin_refund.transactionid,
        }
        assert all(row['result_side'] == 'CANCELLED' for row in outstanding)
        assert response.context['total_unclaimed_all'] == 1200
        assert response.context['admin_unclaimed_all'] == 400
        assert response.context['outstanding_payout_count_all'] == 3
        assert response.context['outstanding_payout_total_all'] == 1600
        assert 'CANCELLED REFUND' in response.content.decode()

    def test_event_report_can_toggle_tellers_without_bets(
        self, admin_client, teller_user, teller_group, django_user_model,
        event_with_fight,
    ):
        active_teller = django_user_model.objects.create_user(
            username='active-teller',
        )
        active_teller.groups.add(teller_group)
        teller_user.groups.add(teller_group)
        _place_bet(active_teller, 500.0)

        active_only = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        active_content = active_only.content.decode()
        active_usernames = [
            row['user'].username for row in active_only.context['teller_data']
        ]
        assert active_teller.username in active_usernames
        assert teller_user.username not in active_usernames
        assert 'Show all tellers' in active_content

        show_all = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}'
            '&show_all_tellers=1',
        )
        all_content = show_all.content.decode()
        all_usernames = [
            row['user'].username for row in show_all.context['teller_data']
        ]
        assert active_teller.username in all_usernames
        assert teller_user.username in all_usernames
        assert 'name="show_all_tellers" value="1"' in all_content
        assert 'checked' in all_content

    def test_event_report_coh_adds_initial_fund_to_expected_cash(
        self, admin_client, admin_user, teller_user, event_with_fight,
    ):
        _place_bet(teller_user, 500.0)
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=10000.0,
            affects_admin_fund=False,
        )
        close_out = services.close_teller_station(
            teller_user,
            event=event_with_fight,
        )
        services.register_teller_cash_count(
            close_out.pk,
            10450.0,
            admin_user,
        )
        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )

        teller_stats = next(
            row for row in response.context['teller_data']
            if row['user'] == teller_user
        )
        assert teller_stats['initial_fund'] == 10000
        assert teller_stats['reporting_coh'] == 20500
        assert response.context['total_reporting_coh_all'] == 20500
        assert response.context['total_initial_fund_all'] == 10000
        content = response.content.decode()
        teller_table = content[content.index('<table id="er-teller-table"'):]
        assert (
            teller_table.index('Fight #')
            < teller_table.index('COH')
            < teller_table.index('Petty')
            < teller_table.index('Expected')
        )

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
        assert response.context['total_on_hand_all'] == -100.0
        assert response.context['total_expected_all'] == 3000.0
        assert response.context['total_actual_all'] == 3100.0
        assert response.context['total_variance_all'] == 100.0

    def test_event_report_shows_admin_breakdown_when_closed(
        self, admin_client, admin_user, event_with_fight,
    ):
        Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=2500.0,
            cashier=str(admin_user),
            registered=True,
        )
        TellerTransaction.objects.create(
            user=admin_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=500.0,
            affects_admin_fund=True,
        )

        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Admin Performance Breakdown' in content
        assert 'Shared Admin Fund' in content
        assert 'Expected Cash on Hand' in content
        assert 'Initial Funds from Bank' in content
        assert 'Additional Funds from Bank' in content
        assert 'Total from Bank' in content
        assert 'Advanced to Bank' in content
        assert 'Test Admin' in content
        assert '2500' in content.replace(',', '')
        assert 'Export Fund Summary' in content

    def test_event_report_shows_shared_fund_bank_totals(
        self, admin_client, admin_user, event_with_fight, default_settings,
    ):
        event_with_fight.admin_opening_fund = 50000.0
        event_with_fight.save(update_fields=['admin_opening_fund'])
        AdminBankTransaction.objects.create(
            event=event_with_fight,
            admin=admin_user,
            transaction_type=AdminBankTransaction.BORROW,
            amount=20000.0,
        )
        AdminBankTransaction.objects.create(
            event=event_with_fight,
            admin=admin_user,
            transaction_type=AdminBankTransaction.REMIT,
            amount=5000.0,
        )

        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode().replace(',', '')
        assert 'Shared Admin Fund' in content
        assert '50000' in content  # initial event fund
        assert '20000' in content  # additional bank borrowing
        assert '70000' in content  # opening 50k + borrow 20k
        assert '5000' in content   # remitted to bank
        assert 'Admin Wagers' in content
        assert 'Admin Payouts' in content
        assert 'Teller Borrows' in content
        assert 'Net Bank Funding + Admin Wagers' in content

    def test_event_report_admin_payouts_exclude_legacy_from_totals(
        self, admin_client, admin_user, event_with_fight,
    ):
        Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=5000.0,
            cashier=admin_user.username,
            registered=True,
        )
        TellerTransaction.objects.create(
            user=admin_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=1000.0,
            affects_admin_fund=True,
        )
        TellerTransaction.objects.create(
            user=admin_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=500.0,
            affects_admin_fund=False,
        )

        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        content = response.content.decode().replace(',', '')
        assert response.status_code == 200
        assert content.count('1000') >= 1
        assert '500' not in content.split('Admin Payouts')[1].split('Teller Remits')[0]

    def test_event_report_hides_admin_breakdown_for_active_event(
        self, admin_client, admin_user, event_with_fight,
    ):
        Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=1000.0,
            cashier=str(admin_user),
            registered=True,
        )

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert '<div id="er-title">Event Report</div>' in content
        assert 'Admin Performance Breakdown' not in content

    def test_event_report_shows_teller_initial_fund(
        self, admin_client, teller_user, event_with_fight, teller_status_online,
        default_settings,
    ):
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=default_settings.teller_initial_fund,
            affects_admin_fund=False,
        )

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode().replace(',', '')
        assert response.context['teller_data'] == []
        assert response.context['total_opening_fund_recon'] == default_settings.teller_initial_fund
        assert 'Initial Funds Issued' in content
        assert str(int(default_settings.teller_initial_fund)) in content

    def test_event_report_excludes_zero_bet_tellers_from_table(
        self, admin_client, teller_user, teller_user2, event_with_fight,
        teller_status_online, default_settings,
    ):
        _place_bet(teller_user, 2000.0)
        TellerTransaction.objects.create(
            user=teller_user2,
            transaction_type=TellerTransaction.COLLECT,
            amount=default_settings.teller_initial_fund,
            affects_admin_fund=False,
        )

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        usernames = [row['user'].username for row in response.context['teller_data']]
        assert teller_user.username in usernames
        assert teller_user2.username not in usernames
        assert response.context['teller_station_count'] == 1
        assert response.context['total_opening_fund_all'] == 0.0
        assert response.context['total_opening_fund_recon'] == default_settings.teller_initial_fund

    def test_event_report_includes_admin_bets_in_teller_breakdown(
        self, admin_client, admin_user, teller_user, event_with_fight, teller_status_online,
    ):
        _place_bet(teller_user, 1500.0)
        Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=3200.0,
            cashier=str(admin_user),
            registered=True,
        )

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Teller Performance Breakdown' in content
        assert 'Test Admin' in content
        assert '(Admin)' in content
        assert '3200' in content.replace(',', '')
        assert response.context['admin_bets_station_count'] == 1
        assert response.context['admin_bets_in_teller_section'] == 3200.0

    def test_event_report_admin_breakdown_shows_bank_borrowed(
        self, admin_client, admin_user, event_with_fight,
    ):
        AdminBankTransaction.objects.create(
            event=event_with_fight,
            admin=admin_user,
            transaction_type=AdminBankTransaction.BORROW,
            amount=15000.0,
        )

        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Borrowed from Bank' in content
        assert '15000' in content.replace(',', '')
        assert response.context['admin_bank_borrowed_all'] == 15000.0
        assert len(response.context['admin_data']) == 1

    def test_event_report_cash_reconciliation_excludes_admin_from_teller_cash(
        self, admin_client, admin_user, teller_user, event_with_fight,
        teller_status_online, default_settings,
    ):
        event_with_fight.admin_opening_fund = default_settings.admin_initial_fund
        event_with_fight.save(update_fields=['admin_opening_fund'])

        _place_bet(teller_user, 5000.0)
        Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=2500.0,
            cashier=str(admin_user),
            registered=True,
        )
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=default_settings.teller_initial_fund,
            affects_admin_fund=False,
        )

        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        assert response.status_code == 200
        recon = response.context['cash_reconciliation']
        assert recon is not None
        assert recon['earnings_vs_betting_surplus'] == pytest.approx(0.0)
        assert recon['teller_cash_on_hand'] == pytest.approx(
            5000.0 + default_settings.teller_initial_fund,
        )
        assert response.context['total_on_hand_all'] == pytest.approx(
            recon['teller_cash_on_hand'] + 2500.0,
        )

    def test_event_report_table_rows_match_declared_columns(
        self, admin_client, admin_user, teller_user, event_with_fight,
    ):
        _place_bet(teller_user, 1000.0)
        Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=500.0,
            cashier=admin_user.username,
            registered=True,
        )
        event_with_fight.is_active = False
        event_with_fight.ended_at = now()
        event_with_fight.save(update_fields=['is_active', 'ended_at'])

        response = admin_client.get(
            f'/administrator/event-report/?event_id={event_with_fight.pk}',
        )
        parser = _TableWidthParser()
        parser.feed(response.content.decode())

        for table_id, expected_width in {
            'er-teller-table': 18,
            'er-admin-fund-table': 12,
            'er-admin-table': 8,
        }.items():
            assert parser.widths[table_id]
            assert set(parser.widths[table_id]) == {expected_width}
