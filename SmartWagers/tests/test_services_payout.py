"""
Tests for payout service functions.

Covers: payout_request (success, wrong-side, already-paid, cross-teller,
unregistered, cancelled-fight, draw-fight), payout_old_ticket,
lookup_wager_for_reprint.
"""

import pytest
from SmartWagers.models import (
    Event, Fight_Results, Fight_Status, TellerTransaction, Totals, Wagers,
)
from SmartWagers import services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fight_result(fightnum, winner, event=None,
                       mtotal=500, wtotal=300, mpayout=95.0, wpayout=158.0):
    """Create a Fight_Results row for the given fight number and winner side."""
    if winner.upper() in ('MERON', 'WALA'):
        odds = 'Llamado' if mtotal == wtotal else ('Dehado' if winner.upper() == 'WALA' else 'Dehado')
    else:
        odds = winner.upper()
    return Fight_Results.objects.create(
        fightnum=fightnum, side=winner.upper(),
        mtotal=mtotal, wtotal=wtotal,
        mpayout=mpayout, wpayout=wpayout,
        totalpot=mtotal + wtotal,
        odds=odds,
        event=event,
    )


def _make_registered_wager(fightnum, side, amount, cashier):
    return Wagers.objects.create(
        fightnum=fightnum, side=side, wager=amount,
        cashier=cashier, registered=True, cashed_out=False,
    )


# ---------------------------------------------------------------------------
# payout_request — winning ticket
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPayoutRequestSuccess:

    def test_winning_meron_ticket_returns_payout_data(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=active_event, mtotal=500, wtotal=300,
                           mpayout=95.0, wpayout=158.0)
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('error') is None
        assert 'Total_Payout' in result

    def test_winning_wala_ticket_returns_payout_data(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'WALA', 300, teller_user.username)
        _make_fight_result(1, 'WALA', event=active_event, mtotal=500, wtotal=300,
                           mpayout=158.0, wpayout=95.0)
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('error') is None

    def test_payout_marks_wager_cashed_out(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=active_event)
        services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        w.refresh_from_db()
        assert w.cashed_out is True

    def test_payout_creates_teller_transaction(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=active_event)
        services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.PAYOUT
        ).exists()

    def test_payout_total_equals_wager_times_multiplier(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 100, teller_user.username)
        # mpayout = 95.0 means multiplier = 0.95
        _make_fight_result(1, 'MERON', event=active_event,
                           mtotal=500, wtotal=300, mpayout=95.0, wpayout=158.0)
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        expected = services.truncate_payout_to_pesos(100 * round(95.0 / 100, 4))  # = 95
        assert float(result['Total_Payout']) == pytest.approx(expected, rel=1e-3)

    def test_payout_drops_centavos_without_rounding(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 200, teller_user.username)
        # 200 * 0.8275 = 165.50 -> truncate to 165 (not round to 166)
        _make_fight_result(1, 'MERON', event=active_event,
                           mtotal=500, wtotal=300, mpayout=82.75, wpayout=158.0)
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('error') is None
        assert float(result['Total_Payout']) == 165.0
        assert result['Total_Payout'] == '165'

    def test_live_and_old_ticket_payout_agree(self, teller_user, default_settings):
        from datetime import timedelta
        from django.utils.timezone import now as tz_now

        active = Event.objects.create(name='Live', is_active=True)
        w_live = _make_registered_wager(1, 'MERON', 100, teller_user.username)
        _make_fight_result(1, 'MERON', event=active, mpayout=95.37, wpayout=158.0)
        live = services.payout_request(
            w_live.transactionid, requesting_cashier=teller_user.username,
        )

        past = Event.objects.create(name='Past', is_active=False)
        past.started_at = tz_now() - timedelta(hours=2)
        past.ended_at = tz_now() + timedelta(hours=1)
        past.save()
        w_old = _make_registered_wager(2, 'MERON', 100, teller_user.username)
        _make_fight_result(2, 'MERON', event=past, mpayout=95.37, wpayout=158.0)
        old = services.payout_old_ticket(past, teller_user.username, w_old.transactionid)

        assert live.get('error') is None
        assert old['ok'] is True
        assert float(live['Total_Payout']) == pytest.approx(old['payout_amount'], rel=1e-6)
        assert float(live['multiplier']) == pytest.approx(old['multiplier'], rel=1e-6)

    def test_missing_cashier_user_does_not_cash_out(self, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 500, 'ghost_cashier')
        _make_fight_result(1, 'MERON', event=active_event)
        result = services.payout_request(w.transactionid, requesting_cashier='ghost_cashier')
        assert result.get('error') == 'cashier_not_found'
        w.refresh_from_db()
        assert w.cashed_out is False
        assert not TellerTransaction.objects.filter(
            transaction_type=TellerTransaction.PAYOUT,
        ).exists()


# ---------------------------------------------------------------------------
# payout_request — error scenarios
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPayoutRequestErrors:

    def test_wrong_side_returns_wrongside_error(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'WALA', 300, teller_user.username)
        _make_fight_result(1, 'MERON', event=active_event)  # MERON won, WALA lost
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('error') == 'wrongside'

    def test_already_cashed_out_returns_alreadypaid(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        w.cashed_out = True
        w.save()
        _make_fight_result(1, 'MERON', event=active_event)
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('error') == 'alreadypaid'
        assert result.get('reprint_available') is True
        assert result['receipt']['receipt_type'] == 'payout'
        assert result['receipt']['transaction_id'] == w.transactionid
        assert float(result['receipt']['Total_Payout']) == pytest.approx(475.0)

    def test_cross_teller_returns_wrong_teller_error(self, teller_user, teller_user2,
                                                      default_settings, active_event):
        # Wager was placed by teller_user
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=active_event)
        # teller_user2 tries to pay it out
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user2.username)
        assert result.get('error') == 'wrong_teller'

    def test_cross_teller_cannot_reprint_already_paid_payout(
        self, teller_user, teller_user2, default_settings, active_event,
    ):
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        w.cashed_out = True
        w.save()
        _make_fight_result(1, 'MERON', event=active_event)
        result = services.payout_request(
            w.transactionid, requesting_cashier=teller_user2.username,
        )
        assert result.get('error') == 'wrong_teller'
        assert result.get('reprint_available') is not True
        assert 'receipt' not in result

    def test_nonexistent_transaction_returns_notfound(self, teller_user, active_event):
        result = services.payout_request('999999')
        assert result.get('error') == 'notfound'

    def test_scanner_stripped_leading_zeros_still_finds_ticket(
        self, teller_user, default_settings, active_event,
    ):
        """Barcode scanners often emit 123 instead of 000123."""
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=active_event)
        assert w.transactionid.startswith('0')

        unpadded = str(int(w.transactionid))
        result = services.payout_request(unpadded, requesting_cashier=teller_user.username)

        assert 'error' not in result
        assert result['transaction_id'] == w.transactionid

    def test_normalize_wager_transaction_id_pads_digits(self):
        assert services.normalize_wager_transaction_id('123') == '000123'
        assert services.normalize_wager_transaction_id(' 000456 ') == '000456'
        assert services.normalize_wager_transaction_id('SABC123') == 'SABC123'

    def test_missing_cashier_account_blocks_payout(self, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 500, 'deleted-teller')
        _make_fight_result(1, 'MERON', event=active_event)

        result = services.payout_request(w.transactionid)

        assert result.get('error') == 'cashier_not_found'
        w.refresh_from_db()
        assert w.cashed_out is False
        assert not TellerTransaction.objects.filter(
            transaction_type=TellerTransaction.PAYOUT,
        ).exists()

    def test_unregistered_wager_returns_notfound(self, teller_user, active_event):
        """A pending (registered=False) wager must not be payable."""
        w = Wagers.objects.create(
            fightnum=1, side='MERON', wager=200,
            cashier=teller_user.username, registered=False,
        )
        result = services.payout_request(w.transactionid)
        assert result.get('error') == 'notfound'

    def test_no_fight_result_returns_notfound(self, teller_user, active_event):
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        # No Fight_Results row — fight hasn't ended yet
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('error') == 'notfound'

    def test_payout_exceeds_cash_on_hand_returns_error(
        self, teller_user, default_settings, active_event,
    ):
        """Teller remitted all cash — cannot pay out a winning ticket."""
        w = _make_registered_wager(1, 'MERON', 100, teller_user.username)
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=100,
            received=True,
        )
        _make_fight_result(1, 'MERON', event=active_event, mpayout=95.0)
        result = services.payout_request(
            w.transactionid, requesting_cashier=teller_user.username,
        )
        assert result.get('error') == 'exceeds_cash_on_hand'
        assert result.get('required') == pytest.approx(95.0)
        assert result.get('balance') == pytest.approx(0.0)
        w.refresh_from_db()
        assert w.cashed_out is False
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type=TellerTransaction.PAYOUT,
        ).exists()

    def test_payout_exceeds_cash_on_hand_is_logged(
        self, teller_user, default_settings, active_event,
    ):
        from unittest.mock import patch
        w = _make_registered_wager(1, 'MERON', 100, teller_user.username)
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=100,
            received=True,
        )
        _make_fight_result(1, 'MERON', event=active_event, mpayout=95.0)
        with patch('SmartWagers.services.logger.warning') as mock_warn:
            services.payout_request(
                w.transactionid, requesting_cashier=teller_user.username,
            )
        assert mock_warn.called
        logged = ' '.join(str(c) for c in mock_warn.call_args_list)
        assert 'PAYOUT REJECTED' in logged
        assert 'exceeds_cash_on_hand' in logged

    def test_cancelled_refund_exceeds_cash_on_hand(
        self, teller_user, default_settings, active_event,
    ):
        w = _make_registered_wager(1, 'MERON', 400, teller_user.username)
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=400,
            received=True,
        )
        Fight_Results.objects.create(
            fightnum=1, side='CANCELLED', mtotal=400, wtotal=0,
            mpayout=0, wpayout=0, totalpot=400, odds='CANCELLED', event=active_event,
        )
        result = services.payout_request(
            w.transactionid, requesting_cashier=teller_user.username,
        )
        assert result.get('error') == 'exceeds_cash_on_hand'
        w.refresh_from_db()
        assert w.cashed_out is False


# ---------------------------------------------------------------------------
# payout_request — special outcomes
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPayoutRequestSpecialOutcomes:

    def test_cancelled_fight_refunds_wager(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 400, teller_user.username)
        Fight_Results.objects.create(
            fightnum=1, side='CANCELLED', mtotal=400, wtotal=0,
            mpayout=0, wpayout=0, totalpot=400, odds='CANCELLED', event=active_event,
        )
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('side') == 'CANCELLED'
        assert float(result['wager'].replace(',', '')) == 400
        assert result.get('print_required') is True
        assert result['receipt']['receipt_type'] == 'cancel_refund'
        assert result['receipt']['side'] == 'CANCELLED'
        assert result['receipt']['odds'] == 'FULL REFUND'
        assert float(result['receipt']['Total_Payout']) == pytest.approx(400.0)

        reprint = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert reprint.get('error') == 'alreadypaid'
        assert reprint.get('reprint_available') is True
        assert reprint['receipt']['receipt_type'] == 'cancel_refund'

    def test_draw_fight_refunds_wager(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'WALA', 300, teller_user.username)
        Fight_Results.objects.create(
            fightnum=1, side='DRAW', mtotal=300, wtotal=300,
            mpayout=0, wpayout=0, totalpot=600, odds='DRAW', event=active_event,
        )
        result = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert result.get('side') == 'DRAW'
        assert result.get('print_required') is True
        assert result['receipt']['receipt_type'] == 'draw_refund'
        assert result['receipt']['side'] == 'DRAW'
        assert result['receipt']['odds'] == 'FULL REFUND'
        assert float(result['receipt']['Total_Payout']) == pytest.approx(300.0)

        reprint = services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        assert reprint.get('error') == 'alreadypaid'
        assert reprint.get('reprint_available') is True
        assert reprint['receipt']['receipt_type'] == 'draw_refund'

    def test_cancelled_payout_marks_cashed_out(self, teller_user, default_settings, active_event):
        w = _make_registered_wager(1, 'MERON', 200, teller_user.username)
        Fight_Results.objects.create(
            fightnum=1, side='CANCELLED', mtotal=200, wtotal=0,
            mpayout=0, wpayout=0, totalpot=200, odds='CANCELLED', event=active_event,
        )
        services.payout_request(w.transactionid, requesting_cashier=teller_user.username)
        w.refresh_from_db()
        assert w.cashed_out is True


# ---------------------------------------------------------------------------
# payout_old_ticket
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPayoutOldTicket:

    def _ended_event(self):
        from django.utils.timezone import now
        from datetime import timedelta
        event = Event.objects.create(name='Past Event', is_active=False)
        # started_at 2 h ago, ended_at 1 h in the future so wagers
        # created during the test fall squarely inside the window.
        event.started_at = now() - timedelta(hours=2)
        event.ended_at = now() + timedelta(hours=1)
        event.save()
        return event

    def test_winning_ticket_from_past_event(self, teller_user, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=event, mpayout=95.0)
        result = services.payout_old_ticket(event, teller_user.username, w.transactionid)
        assert result['ok'] is True
        assert result['result'] == 'winner'

    def test_losing_ticket_returns_not_a_winner(self, teller_user, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'WALA', 300, teller_user.username)
        _make_fight_result(1, 'MERON', event=event)
        result = services.payout_old_ticket(event, teller_user.username, w.transactionid)
        assert result['ok'] is False
        assert result['error'] == 'not_a_winner'

    def test_already_claimed_returns_error(self, teller_user, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        w.cashed_out = True
        w.save()
        _make_fight_result(1, 'MERON', event=event)
        result = services.payout_old_ticket(event, teller_user.username, w.transactionid)
        assert result['error'] == 'already_claimed'

    def test_notfound_when_wrong_teller(self, teller_user, teller_user2, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        _make_fight_result(1, 'MERON', event=event)
        # teller_user2 queries for teller_user's ticket
        result = services.payout_old_ticket(event, teller_user2.username, w.transactionid)
        assert result['error'] == 'notfound'

    def test_cancelled_fight_refunds_in_past_event(self, teller_user, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'WALA', 200, teller_user.username)
        Fight_Results.objects.create(
            fightnum=1, side='CANCELLED', mtotal=0, wtotal=200,
            mpayout=0, wpayout=0, totalpot=200, odds='CANCELLED', event=event,
        )
        result = services.payout_old_ticket(event, teller_user.username, w.transactionid)
        assert result['ok'] is True
        assert result['result'] == 'cancelled'

    def test_no_fight_result_returns_no_result_yet(self, teller_user, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'MERON', 500, teller_user.username)
        result = services.payout_old_ticket(event, teller_user.username, w.transactionid)
        assert result['error'] == 'no_result_yet'

    def test_missing_cashier_user_does_not_cash_out(self, default_settings):
        event = self._ended_event()
        w = _make_registered_wager(1, 'MERON', 500, 'ghost_cashier')
        _make_fight_result(1, 'MERON', event=event, mpayout=95.0)
        result = services.payout_old_ticket(event, 'ghost_cashier', w.transactionid)
        assert result['ok'] is False
        assert result['error'] == 'cashier_not_found'
        w.refresh_from_db()
        assert w.cashed_out is False
        assert not TellerTransaction.objects.filter(
            transaction_type=TellerTransaction.PAYOUT,
        ).exists()


# ---------------------------------------------------------------------------
# lookup_wager_for_reprint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLookupWagerForReprint:

    def test_returns_receipt_payload_for_valid_wager(self, active_event):
        w = Wagers.objects.create(
            fightnum=1, side='MERON', wager=300,
            cashier='teller1', registered=True,
        )
        payload = services.lookup_wager_for_reprint(w.transactionid)
        assert payload is not None
        assert payload['transaction_id'] == w.transactionid
        assert payload['side'] == 'MERON'
        assert payload['fightnum'] == 1

    def test_returns_none_for_nonexistent_transaction(self, active_event):
        assert services.lookup_wager_for_reprint('999999') is None

    def test_returns_none_for_unregistered_wager(self, active_event):
        w = Wagers.objects.create(
            fightnum=1, side='MERON', wager=100,
            cashier='teller1', registered=False,
        )
        assert services.lookup_wager_for_reprint(w.transactionid) is None

    def test_payload_contains_all_required_keys(self, active_event):
        w = Wagers.objects.create(
            fightnum=2, side='WALA', wager=500,
            cashier='teller1', registered=True,
        )
        payload = services.lookup_wager_for_reprint(w.transactionid)
        for key in ('receipt_type', 'event_name', 'transaction_id', 'fightnum',
                    'side', 'amount', 'cashier', 'date'):
            assert key in payload, f"Missing key: {key}"
