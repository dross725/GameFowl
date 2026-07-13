"""
Tests for event lifecycle and teller fund service functions.

Covers: start_event, end_event, get_active_event, get_event_scope,
_get_teller_outstanding_balance, _reset_teller_balances,
_issue_initial_teller_funds.
"""

import pytest
from django.utils.timezone import now
from SmartWagers.models import (
    Event, TellerStatus, TellerTransaction, Wagers,
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

    def test_returns_most_recent_active_when_multiple(self):
        """Service returns the most recently started active event."""
        Event.objects.create(name='Old Active', is_active=True)
        newer = Event.objects.create(name='Newer Active', is_active=True)
        result = services.get_active_event()
        assert result.pk == newer.pk


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

    def test_skips_offline_teller(
            self, default_settings, teller_user, teller_status_offline):
        services._issue_initial_teller_funds()
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.COLLECT
        ).exists()

    def test_skips_when_initial_fund_is_zero(self, teller_user, teller_status_online):
        from SmartWagers.models import Settings
        Settings.objects.create(teller_initial_fund=0.0, plasada=0.05)
        services._issue_initial_teller_funds()
        assert not TellerTransaction.objects.filter(user=teller_user).exists()


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
        assert TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.REMIT
        ).exists()

    def test_zero_balance_no_transaction_created(
            self, default_settings, active_event, teller_user):
        services._reset_teller_balances()
        assert TellerTransaction.objects.filter(user=teller_user).count() == 0
