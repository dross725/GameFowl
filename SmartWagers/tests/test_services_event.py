"""
Tests for event lifecycle and teller fund service functions.

Covers: start_event, end_event, get_active_event, get_event_scope,
_get_teller_outstanding_balance, _reset_teller_balances,
_issue_initial_teller_funds.
"""

import pytest
from datetime import timedelta
from django.utils.timezone import now
from SmartWagers.models import (
    AdminBankTransaction, Event, TellerStatus, TellerTransaction, Wagers,
)
from SmartWagers import services


# ---------------------------------------------------------------------------
# start_event
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStartEvent:

    def test_creates_active_event(self, default_settings):
        event = services.start_event('Night Derby 1')
        assert event.is_active is True
        assert event.name == 'Night Derby 1'

    def test_only_one_active_event_after_start(self, default_settings):
        services.start_event('Event A')
        services.start_event('Event B')
        assert Event.objects.filter(is_active=True).count() == 1

    def test_previous_event_deactivated_on_new_start(self, default_settings):
        e1 = services.start_event('Event A')
        services.start_event('Event B')
        e1.refresh_from_db()
        assert e1.is_active is False

    def test_previous_event_gets_ended_at_on_new_start(self, default_settings):
        e1 = services.start_event('Event A')
        services.start_event('Event B')
        e1.refresh_from_db()
        assert e1.ended_at is not None

    def test_fight_status_reset_to_0_on_start(self, default_settings):
        services.start_event('Night Derby')
        _, _, _, fn = services.get_fight_status()
        assert fn == 0

    def test_initial_fund_issued_for_online_tellers(
            self, default_settings, teller_user, teller_status_online):
        before = TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.COLLECT
        ).count()
        services.start_event('Event A')
        after = TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.COLLECT
        ).count()
        assert after == before + 1

    def test_no_initial_fund_for_offline_tellers(
            self, default_settings, teller_user, teller_status_offline):
        services.start_event('Event A')
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.COLLECT
        ).exists()

    def test_admin_opening_fund_is_snapshotted_without_per_admin_transaction(
            self, default_settings, admin_user):
        event = services.start_event('Event A')
        assert event.admin_opening_fund == default_settings.admin_initial_fund
        assert not TellerTransaction.objects.filter(user=admin_user).exists()


# ---------------------------------------------------------------------------
# end_event
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEndEvent:

    def test_end_event_marks_inactive(self, active_event):
        services.end_event()
        active_event.refresh_from_db()
        assert active_event.is_active is False

    def test_end_event_sets_ended_at(self, active_event):
        services.end_event()
        active_event.refresh_from_db()
        assert active_event.ended_at is not None

    def test_end_event_returns_event_object(self, active_event):
        result = services.end_event()
        assert result is not None
        assert result.pk == active_event.pk

    def test_end_event_returns_none_when_no_active_event(self):
        result = services.end_event()
        assert result is None


# ---------------------------------------------------------------------------
# get_active_event
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetActiveEvent:

    def test_returns_active_event(self, active_event):
        result = services.get_active_event()
        assert result is not None
        assert result.pk == active_event.pk

    def test_returns_none_when_no_active_event(self):
        assert services.get_active_event() is None

    def test_returns_active_event_when_newer_event_is_inactive(self):
        active = Event.objects.create(name='Active', is_active=True)
        Event.objects.create(name='Newer Inactive', is_active=False)
        result = services.get_active_event()
        assert result.pk == active.pk


# ---------------------------------------------------------------------------
# get_event_scope
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetEventScope:

    def test_returns_active_event_with_apply_end_bound_true(self, active_event):
        event, apply_end = services.get_event_scope()
        assert event.pk == active_event.pk
        assert apply_end is True

    def test_returns_last_event_with_apply_end_bound_false_when_no_active(self):
        past = Event.objects.create(name='Past', is_active=False)
        event, apply_end = services.get_event_scope()
        assert event.pk == past.pk
        assert apply_end is False

    def test_returns_none_event_when_no_events_exist(self):
        event, apply_end = services.get_event_scope()
        assert event is None


# ---------------------------------------------------------------------------
# _get_teller_outstanding_balance
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetTellerOutstandingBalance:

    def test_balance_is_bets_minus_remits_plus_collects_minus_payouts(
            self, teller_user, active_event):
        """balance = bets(500) - remit(200) + collect(100) - payout(50) = 350"""
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=500,
            cashier=teller_user.username, registered=True,
        )
        TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.REMIT, amount=200,
        )
        TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.COLLECT, amount=100,
        )
        TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.PAYOUT, amount=50,
        )
        balance = services._get_teller_outstanding_balance(teller_user, event=active_event)
        assert balance == pytest.approx(350.0)

    def test_zero_balance_when_no_activity(self, teller_user, active_event):
        balance = services._get_teller_outstanding_balance(teller_user, event=active_event)
        assert balance == 0.0

    def test_scoped_to_event_window(self, teller_user):
        """Wagers outside the event window must be excluded."""
        old_event = Event.objects.create(name='Old', is_active=False)
        old_event.ended_at = now()
        old_event.save()

        new_event = Event.objects.create(name='New', is_active=True)

        # Old wager before the new event
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=999,
            cashier=teller_user.username, registered=True,
            created_at=old_event.started_at,
        )
        balance = services._get_teller_outstanding_balance(teller_user, event=new_event)
        assert balance == 0.0

    def test_multiple_bets_sum_correctly(self, teller_user, active_event):
        for _ in range(5):
            Wagers.objects.create(
                fightnum=1, side='MERON', wager=100,
                cashier=teller_user.username, registered=True,
            )
        balance = services._get_teller_outstanding_balance(teller_user, event=active_event)
        assert balance == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# _issue_initial_teller_funds
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIssueInitialTellerFunds:

    def test_issues_collect_transaction_for_online_teller(
            self, default_settings, teller_user, teller_status_online):
        services._issue_initial_teller_funds()
        txns = TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.COLLECT
        )
        assert txns.count() == 1
        assert txns.first().amount == default_settings.teller_initial_fund
        assert txns.first().affects_admin_fund is False

    def test_skips_offline_teller(
            self, default_settings, teller_user, teller_status_offline):
        services._issue_initial_teller_funds()
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.COLLECT
        ).exists()

    def test_skips_when_initial_fund_is_zero(self, teller_user, teller_status_online):
        from SmartWagers.models import Settings
        Settings.objects.create(
            teller_initial_fund=0.0,
            admin_initial_fund=0.0,
            plasada=0.05,
        )
        services._issue_initial_teller_funds()
        assert not TellerTransaction.objects.filter(user=teller_user).exists()

    def test_does_not_issue_individual_fund_for_admin(
            self, default_settings, admin_user):
        services._issue_initial_teller_funds()
        assert not TellerTransaction.objects.filter(user=admin_user).exists()

    def test_dual_role_admin_does_not_receive_teller_opening_fund(
            self, default_settings, admin_user, teller_group):
        admin_user.groups.add(teller_group)
        TellerStatus.objects.create(user=admin_user, is_online=True)

        services._issue_initial_teller_funds()

        assert not TellerTransaction.objects.filter(user=admin_user).exists()


# ---------------------------------------------------------------------------
# shared admin fund
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSharedAdminFund:

    def test_opening_fund_is_shared_once_across_admins(
            self, active_event, admin_user, admin_group):
        from django.contrib.auth.models import User
        second_admin = User.objects.create_user(username='admin2')
        second_admin.groups.add(admin_group)

        summary = services.get_admin_fund_summary(event=active_event)

        assert summary['balance'] == active_event.admin_opening_fund
        assert summary['bank_borrowed'] == active_event.admin_opening_fund

    def test_bank_borrow_and_remit_change_shared_balance(
            self, active_event, admin_user):
        AdminBankTransaction.objects.create(
            event=active_event,
            admin=admin_user,
            transaction_type=AdminBankTransaction.BORROW,
            amount=25000,
        )
        AdminBankTransaction.objects.create(
            event=active_event,
            admin=admin_user,
            transaction_type=AdminBankTransaction.REMIT,
            amount=5000,
        )

        summary = services.get_admin_fund_summary(event=active_event)

        assert summary['bank_borrowed'] == 125000
        assert summary['bank_remitted'] == 5000
        assert summary['net_bank_funding'] == 120000
        assert summary['balance'] == 120000

    def test_teller_remit_counts_only_after_received(
            self, active_event, admin_user, teller_user):
        txn = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=7000,
            received=False,
        )
        assert services.get_admin_fund_summary(
            event=active_event,
        )['balance'] == 100000

        txn.received = True
        txn.save(update_fields=['received'])
        assert services.get_admin_fund_summary(
            event=active_event,
        )['balance'] == 107000

    def test_teller_borrow_reduces_fund_but_opening_float_does_not(
            self, active_event, admin_user, teller_user):
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=10000,
            affects_admin_fund=False,
        )
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=3000,
            affects_admin_fund=True,
        )

        summary = services.get_admin_fund_summary(event=active_event)
        assert summary['teller_borrows'] == 3000
        assert summary['balance'] == 97000

    def test_admin_wagers_and_payouts_are_pooled(
            self, active_event, admin_user):
        Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=8000,
            cashier=admin_user.username,
            registered=True,
        )
        TellerTransaction.objects.create(
            user=admin_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=2500,
        )

        summary = services.get_admin_fund_summary(event=active_event)
        assert summary['admin_wagers'] == 8000
        assert summary['admin_payouts'] == 2500
        assert summary['balance'] == 105500

    def test_legacy_admin_payout_does_not_change_shared_fund(
            self, active_event, admin_user):
        TellerTransaction.objects.create(
            user=admin_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=2500,
            affects_admin_fund=False,
        )
        summary = services.get_admin_fund_summary(event=active_event)
        assert summary['admin_payouts'] == 0
        assert summary['balance'] == 100000

    def test_admin_payout_limit_uses_shared_fund(
            self, active_event, admin_user):
        assert services._payout_exceeds_cash_on_hand(
            admin_user.username, 100000, 'TEST001',
        ) is None
        rejected = services._payout_exceeds_cash_on_hand(
            admin_user.username, 100001, 'TEST002',
        )
        assert rejected['error'] == 'exceeds_cash_on_hand'
        assert rejected['balance'] == 100000


# ---------------------------------------------------------------------------
# _reset_teller_balances
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestResetTellerBalances:

    def test_positive_balance_creates_remit(
            self, default_settings, active_event, teller_user, teller_group):
        """Teller owes house (balance > 0) → auto-REMIT to zero."""
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=1000,
            cashier=teller_user.username, registered=True,
        )
        services._reset_teller_balances()
        settlement = TellerTransaction.objects.get(
            user=teller_user, transaction_type=TellerTransaction.REMIT
        )
        assert settlement.affects_admin_fund is False

    def test_zero_balance_no_transaction_created(
            self, default_settings, active_event, teller_user):
        services._reset_teller_balances()
        assert TellerTransaction.objects.filter(user=teller_user).count() == 0

    def test_negative_balance_settlement_does_not_debit_admin_fund(
            self, default_settings, active_event, teller_user):
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=500,
        )

        services._reset_teller_balances()

        settlement = TellerTransaction.objects.filter(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
        ).latest('id')
        assert settlement.amount == 500
        assert settlement.affects_admin_fund is False

    def test_settles_last_ended_event_when_no_active_event(
            self, default_settings, teller_user):
        """End → Start workflow must settle the ended event, not lifetime history."""
        event = Event.objects.create(name='Ended Event', is_active=False)
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=2500,
            cashier=teller_user.username, registered=True,
        )
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=default_settings.teller_initial_fund,
            affects_admin_fund=False,
        )
        event.ended_at = now()
        event.save(update_fields=['ended_at'])

        services._reset_teller_balances()

        settlement = TellerTransaction.objects.get(
            user=teller_user, transaction_type=TellerTransaction.REMIT,
        )
        expected_balance = (
            2500 - 0 + default_settings.teller_initial_fund - 0
        )
        assert settlement.amount == pytest.approx(expected_balance)
        assert settlement.affects_admin_fund is False

    def test_end_then_start_settlement_included_in_ended_event_balance(
            self, default_settings, teller_user, teller_status_online):
        """Rollover txns after ended_at must zero the closed event's report balance."""
        event = services.start_event('Event A')
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=2500,
            cashier=teller_user.username, registered=True,
        )
        ended = services.end_event()
        Event.objects.filter(pk=ended.pk).update(
            ended_at=now() - timedelta(hours=1),
        )
        ended.refresh_from_db()

        services.start_event('Event B')

        balance = services._get_teller_outstanding_balance(
            teller_user, event=ended, apply_end_bound=True,
        )
        assert balance == pytest.approx(0)


@pytest.mark.django_db
class TestOnlineTellerFreshBalanceOnEventStart:

    def test_online_teller_balance_resets_to_initial_fund(
            self, default_settings, teller_user, teller_status_online):
        services.start_event('Event A')
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=5000,
            cashier=teller_user.username, registered=True,
        )
        event_b = services.start_event('Event B')
        balance = services._get_teller_outstanding_balance(
            teller_user, event=event_b,
        )
        assert balance == pytest.approx(default_settings.teller_initial_fund)

    def test_online_teller_balance_after_end_then_start(
            self, default_settings, teller_user, teller_status_online):
        services.start_event('Event A')
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=5000,
            cashier=teller_user.username, registered=True,
        )
        services.end_event()
        event_c = services.start_event('Event C')
        balance = services._get_teller_outstanding_balance(
            teller_user, event=event_c,
        )
        assert balance == pytest.approx(default_settings.teller_initial_fund)

    def test_toggle_online_does_not_double_issue_opening_fund(
            self, default_settings, teller_user, teller_status_online):
        event = services.start_event('Event A')
        opening_count = TellerTransaction.objects.filter(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            affects_admin_fund=False,
            created_at__gte=event.started_at,
        ).count()
        assert opening_count == 1

        status = TellerStatus.objects.get(user=teller_user)
        status.is_online = False
        status.save(update_fields=['is_online'])
        status.is_online = True
        status.save(update_fields=['is_online'])

        if not services.teller_has_opening_fund_for_event(teller_user, event):
            services._issue_initial_teller_funds()

        opening_count = TellerTransaction.objects.filter(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            affects_admin_fund=False,
            created_at__gte=event.started_at,
        ).count()
        assert opening_count == 1
        balance = services._get_teller_outstanding_balance(
            teller_user, event=event,
        )
        assert balance == pytest.approx(default_settings.teller_initial_fund)
