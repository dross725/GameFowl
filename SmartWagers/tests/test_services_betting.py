"""
Tests for betting and totals service functions.

Covers: add_wager, add_total, deduct_totals, compute_payout (llamado/dehado/zero-pot),
cancel_bet, is_betting_open, is_match_open, update_control_status.
"""

import pytest
from SmartWagers.models import Fight_Status, Totals, Wagers
from SmartWagers import services


# ---------------------------------------------------------------------------
# Helper: seed an OPEN fight state
# ---------------------------------------------------------------------------

def _open_fight(fightnum=1):
    Fight_Status.objects.all().delete()
    fs = Fight_Status.objects.create(
        fightnum=fightnum, overall_status='OPEN',
        meron_status='OPEN', wala_status='OPEN',
    )
    Totals.objects.create(fightnum=fightnum, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
    Wagers.objects.create(fightnum=fightnum, side='START', wager=0, cashier='System', registered=True)
    return fs


# ---------------------------------------------------------------------------
# add_wager
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAddWager:

    def test_creates_wager_row(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(100, 'MERON', 1, cashier='teller1')
        assert Wagers.objects.filter(pk=w.pk, registered=True).exists()

    def test_wager_is_registered_immediately(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(200, 'WALA', 1, cashier='teller1')
        assert w.registered is True

    def test_meron_updates_mtotal(self, default_settings):
        _open_fight()
        services.add_wager(300, 'MERON', 1, cashier='teller1')
        m, _, _, _, _, _ = services.get_Totals()
        assert m == 300

    def test_wala_updates_wtotal(self, default_settings):
        _open_fight()
        services.add_wager(200, 'WALA', 1, cashier='teller1')
        _, _, w, _, _, _ = services.get_Totals()
        assert w == 200

    def test_totalpot_accumulates(self, default_settings):
        _open_fight()
        services.add_wager(100, 'MERON', 1, cashier='t1')
        services.add_wager(200, 'WALA', 1, cashier='t2')
        _, _, _, _, pot, _ = services.get_Totals()
        assert pot == 300

    def test_creates_new_totals_row_per_wager(self, default_settings):
        _open_fight()
        before = Totals.objects.count()
        services.add_wager(100, 'MERON', 1, cashier='t1')
        services.add_wager(200, 'WALA', 1, cashier='t1')
        assert Totals.objects.count() == before + 2

    def test_multiple_wagers_accumulate_correctly(self, default_settings):
        _open_fight()
        # Distinct cashiers so the 3s duplicate window does not collapse bets.
        for i in range(5):
            services.add_wager(100, 'MERON', 1, cashier=f'teller{i}')
        m, _, _, _, pot, _ = services.get_Totals()
        assert m == 500
        assert pot == 500

    def test_duplicate_window_returns_existing_without_new_row(self, default_settings):
        _open_fight()
        w1, created1 = services.add_wager(250, 'MERON', 1, cashier='teller1')
        w2, created2 = services.add_wager(250, 'MERON', 1, cashier='teller1')
        assert created1 is True
        assert created2 is False
        assert w1.pk == w2.pk
        assert Wagers.objects.filter(
            cashier='teller1', side='MERON', wager=250, registered=True, cancelled=False,
        ).count() == 1
        m, _, _, _, _, _ = services.get_Totals()
        assert m == 250

    def test_idempotent_client_request_id_returns_same_wager(self, default_settings):
        _open_fight()
        request_id = 'aaaaaaaa-bbbb-4ccc-dddd-eeeeeeeeeeee'
        w1, created1 = services.add_wager(
            250, 'MERON', 1, cashier='teller1', client_request_id=request_id,
        )
        w2, created2 = services.add_wager(
            250, 'MERON', 1, cashier='teller1', client_request_id=request_id,
        )
        assert created1 is True
        assert created2 is False
        assert w1.pk == w2.pk
        assert Wagers.objects.filter(client_request_id=request_id.lower()).count() == 1
        m, _, _, _, _, _ = services.get_Totals()
        assert m == 250

    def test_different_client_request_ids_allow_identical_bets(self, default_settings):
        _open_fight()
        w1, created1 = services.add_wager(
            500, 'MERON', 1, cashier='teller1',
            client_request_id='11111111-1111-4111-8111-111111111111',
        )
        w2, created2 = services.add_wager(
            500, 'MERON', 1, cashier='teller1',
            client_request_id='22222222-2222-4222-8222-222222222222',
        )
        assert created1 is True
        assert created2 is True
        assert w1.pk != w2.pk
        m, _, _, _, _, _ = services.get_Totals()
        assert m == 1000

    def test_invalid_client_request_id_is_ignored(self, default_settings):
        _open_fight()
        w1, created1 = services.add_wager(
            100, 'MERON', 1, cashier='teller1', client_request_id='not-a-uuid',
        )
        w2, created2 = services.add_wager(
            100, 'MERON', 1, cashier='teller1', client_request_id='also-invalid',
        )
        assert created1 is True
        assert created2 is False
        assert w1.pk == w2.pk
        assert w1.client_request_id is None

    def test_normalize_client_request_id_lowercases_uuid(self):
        assert services.normalize_client_request_id('AABBCCDD-EEFF-4111-8111-112233445566') == (
            'aabbccdd-eeff-4111-8111-112233445566'
        )

    def test_teller_blocked_when_side_closed(self, default_settings):
        _open_fight()
        Fight_Status.objects.all().update(meron_status='CLOSE')
        with pytest.raises(services.BettingClosedError):
            services.add_wager(100, 'MERON', 1, cashier='teller1', require_side_open=True)

    def test_admin_allowed_when_side_closed_but_match_open(self, default_settings):
        _open_fight()
        Fight_Status.objects.all().update(meron_status='CLOSE')
        w, created = services.add_wager(
            100, 'MERON', 1, cashier='admin1', require_side_open=False,
        )
        assert created is True
        assert w.registered is True

    def test_admin_blocked_when_match_closed(self, default_settings):
        _open_fight()
        Fight_Status.objects.all().update(overall_status='CLOSED')
        with pytest.raises(services.BettingClosedError):
            services.add_wager(100, 'MERON', 1, cashier='admin1', require_side_open=False)


# ---------------------------------------------------------------------------
# compute_payout
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestComputePayout:

    def test_llamado_equal_pots_each_side_payout_near_190(self, default_settings):
        """Equal totals (llamado): return per 100 bet = (total/side) * (1-comm) * 100.
        With 500/500 pot=1000 and comm=0.05: (1000/500) * 0.95 * 100 = 190."""
        m_pay, w_pay = services.compute_payout(500, 500, 1000)
        assert float(m_pay) == pytest.approx(190.0, rel=1e-3)
        assert float(w_pay) == pytest.approx(190.0, rel=1e-3)

    def test_dehado_underdog_return_greater_than_favourite(self, default_settings):
        """Underdog side (smaller pot) returns more per 100 bet than the favourite."""
        m_pay, w_pay = services.compute_payout(500, 200, 700)
        assert float(w_pay) > float(m_pay), "Underdog must return more than favourite"
        assert float(w_pay) > 100.0, "Underdog return must exceed wager"

    def test_favourite_return_less_than_underdog(self, default_settings):
        """Favourite side (larger pot) returns less than the underdog per 100 bet,
        but still returns more than 100 (positive net payout)."""
        m_pay, w_pay = services.compute_payout(500, 200, 700)
        assert float(m_pay) < float(w_pay), "Favourite payout must be less than underdog"
        assert float(m_pay) > 100.0, "Favourite payout must still be positive (>100 total return)"

    def test_zero_meron_pot_returns_zero_for_meron(self, default_settings):
        """No division by zero when one side has no bets."""
        m_pay, w_pay = services.compute_payout(0, 300, 300)
        assert m_pay == 0

    def test_zero_wala_pot_returns_zero_for_wala(self, default_settings):
        m_pay, w_pay = services.compute_payout(300, 0, 300)
        assert w_pay == 0

    def test_zero_both_pots_returns_zeros(self, default_settings):
        m_pay, w_pay = services.compute_payout(0, 0, 0)
        assert m_pay == 0
        assert w_pay == 0

    def test_commission_applied_correctly(self, default_settings):
        """Exact formula: display_payout = (total_pot / side_total) * (1 - plasada) * 100.
        With equal 500/500 pots and plasada=0.05: (1000/500) * 0.95 * 100 = 190.0."""
        comm = 0.05
        expected = (1000 / 500) * (1 - comm) * 100  # = 190.0
        m_pay, _ = services.compute_payout(500, 500, 1000)
        assert float(m_pay) == pytest.approx(expected, rel=1e-4)

    def test_commission_cache_invalidates_when_settings_change(self, default_settings):
        assert services.get_comm_val() == pytest.approx(0.05)
        default_settings.plasada = 0.10
        default_settings.save(update_fields=['plasada'])
        assert services.get_comm_val() == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# add_total / deduct_totals
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAddAndDeductTotals:

    def test_add_total_meron(self, default_settings):
        Totals.objects.create(fightnum=1, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
        services.add_total(200, 'MERON')
        m, _, _, _, pot, _ = services.get_Totals()
        assert m == 200
        assert pot == 200

    def test_add_total_wala(self, default_settings):
        Totals.objects.create(fightnum=1, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
        services.add_total(150, 'WALA')
        _, _, w, _, pot, _ = services.get_Totals()
        assert w == 150
        assert pot == 150

    def test_deduct_totals_reduces_correctly(self, default_settings):
        Totals.objects.create(fightnum=1, mtotal=500, wtotal=300, mpayout=0, wpayout=0, totalpot=800)
        services.deduct_totals('MERON', 200)
        m, _, _, _, pot, _ = services.get_Totals()
        assert m == 300
        assert pot == 600

    def test_deduct_creates_new_totals_row(self, default_settings):
        Totals.objects.create(fightnum=1, mtotal=500, wtotal=0, mpayout=0, wpayout=0, totalpot=500)
        before = Totals.objects.count()
        services.deduct_totals('MERON', 100)
        assert Totals.objects.count() == before + 1


# ---------------------------------------------------------------------------
# is_betting_open / is_match_open
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBettingGates:

    def test_betting_open_when_overall_open_and_side_open(self):
        _open_fight()
        assert services.is_betting_open('MERON') is True
        assert services.is_betting_open('WALA') is True

    def test_betting_closed_when_no_fight_status(self):
        assert services.is_betting_open('MERON') is False

    def test_betting_closed_when_overall_closed(self):
        Fight_Status.objects.create(
            fightnum=1, overall_status='CLOSED', meron_status='CLOSE', wala_status='CLOSE'
        )
        assert services.is_betting_open('MERON') is False

    def test_is_match_open_true_when_overall_open(self):
        _open_fight()
        assert services.is_match_open() is True

    def test_is_match_open_false_when_overall_closed(self):
        Fight_Status.objects.create(
            fightnum=1, overall_status='CLOSED', meron_status='CLOSE', wala_status='CLOSE'
        )
        assert services.is_match_open() is False

    def test_is_match_open_false_when_no_fight_status(self):
        assert services.is_match_open() is False


# ---------------------------------------------------------------------------
# update_control_status (per-side gate)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUpdateControlStatus:

    def test_close_meron_only_wala_still_open(self):
        _open_fight()
        services.update_control_status('MERON', 'CLOSE')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.meron_status == 'CLOSE'
        assert fs.wala_status == 'OPEN'

    def test_close_wala_only_meron_still_open(self):
        _open_fight()
        services.update_control_status('WALA', 'CLOSE')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.wala_status == 'CLOSE'
        assert fs.meron_status == 'OPEN'

    def test_close_both_closes_both(self):
        _open_fight()
        services.update_control_status('BOTH', 'CLOSE')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.meron_status == 'CLOSE'
        assert fs.wala_status == 'CLOSE'

    def test_reopen_side_when_fight_is_closed_restores_overall_open(self):
        """Reopening a side on a CLOSED fight (not terminal) should
        restore overall_status to OPEN."""
        Fight_Status.objects.create(
            fightnum=1, overall_status='CLOSED', meron_status='CLOSE', wala_status='CLOSE'
        )
        services.update_control_status('MERON', 'OPEN')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.overall_status == 'OPEN'

    def test_is_betting_open_meron_false_after_meron_closed(self):
        _open_fight()
        services.update_control_status('MERON', 'CLOSE')
        assert services.is_betting_open('MERON') is False
        assert services.is_betting_open('WALA') is True


# ---------------------------------------------------------------------------
# cancel_bet
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCancelBet:

    def test_cancel_open_bet_deducts_totals(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(500, 'MERON', 1, cashier='teller1')
        services.cancel_bet(w.transactionid)
        m, _, _, _, pot, _ = services.get_Totals()
        assert m == 0
        assert pot == 0

    def test_cancel_open_bet_marks_wager_cancelled(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(300, 'MERON', 1, cashier='teller1')
        tid = w.transactionid
        result = services.cancel_bet(tid)
        wager = Wagers.objects.get(transactionid=tid)
        assert wager.registered is True
        assert wager.cancelled is True
        assert result.get('receipt', {}).get('receipt_type') == 'cancel'
        assert result.get('receipt', {}).get('transaction_id') == tid

    def test_cancel_nonexistent_returns_error(self, default_settings):
        _open_fight()
        result = services.cancel_bet('999999')
        assert result.get('error') == 'notfound'

    def test_cancel_when_match_closed_returns_error(self, default_settings):
        Fight_Status.objects.create(
            fightnum=1, overall_status='CLOSED', meron_status='CLOSE', wala_status='CLOSE'
        )
        Totals.objects.create(fightnum=1, mtotal=500, wtotal=0, mpayout=0, wpayout=0, totalpot=500)
        Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
        w = Wagers.objects.create(fightnum=1, side='MERON', wager=500, cashier='teller1', registered=True)
        result = services.cancel_bet(w.transactionid)
        assert result.get('error') == 'matchnotopen'

    def test_successful_cancel_returns_amount(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(750, 'WALA', 1, cashier='teller1')
        result = services.cancel_bet(w.transactionid)
        assert result.get('message') == 'betcancelled'
        assert '750' in str(result.get('amount', ''))

    def test_cancel_already_cancelled_returns_notfound(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(200, 'MERON', 1, cashier='teller1')
        services.cancel_bet(w.transactionid)
        result = services.cancel_bet(w.transactionid)
        assert result.get('error') == 'notfound'

    def test_cancel_cashed_out_returns_alreadypaid(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(400, 'WALA', 1, cashier='teller1')
        Wagers.objects.filter(pk=w.pk).update(cashed_out=True)
        result = services.cancel_bet(w.transactionid)
        assert result.get('error') == 'alreadypaid'
        wager = Wagers.objects.get(pk=w.pk)
        assert wager.cancelled is False

    def test_cancel_includes_print_required_flag(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(100, 'MERON', 1, cashier='teller1')
        result = services.cancel_bet(w.transactionid)
        assert 'print_required' in result
        assert 'receipt' in result
        assert result['receipt']['receipt_type'] == 'cancel'

    def test_cross_teller_cancel_returns_wrong_teller(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(200, 'MERON', 1, cashier='teller1')
        result = services.cancel_bet(w.transactionid, requesting_cashier='teller2')
        assert result.get('error') == 'wrong_teller'
        assert result.get('original_cashier') == 'teller1'
        wager = Wagers.objects.get(pk=w.pk)
        assert wager.cancelled is False

    def test_owner_teller_can_cancel(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(200, 'WALA', 1, cashier='teller1')
        result = services.cancel_bet(w.transactionid, requesting_cashier='teller1')
        assert result.get('message') == 'betcancelled'
        wager = Wagers.objects.get(pk=w.pk)
        assert wager.cancelled is True

    def test_admin_cancel_without_cashier_still_succeeds(self, default_settings):
        _open_fight()
        w, _ = services.add_wager(300, 'MERON', 1, cashier='teller1')
        result = services.cancel_bet(w.transactionid, requesting_cashier=None)
        assert result.get('message') == 'betcancelled'

# ---------------------------------------------------------------------------
# Wrong-punch amount guard (trailing 3 / 6)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestWrongPunchGuard:

    def test_detects_amounts_ending_in_3_or_6(self):
        assert services.is_wrong_punch_amount(2003) is True
        assert services.is_wrong_punch_amount(2006) is True
        assert services.is_wrong_punch_amount(3) is True
        assert services.is_wrong_punch_amount(6) is True
        assert services.is_wrong_punch_amount(200) is False
        assert services.is_wrong_punch_amount(1000) is False
        assert services.is_wrong_punch_amount(250) is False

    def test_enabled_by_default_when_settings_exist(self, default_settings):
        assert services.is_discard_trailing_3_6_enabled() is True

    def test_can_be_disabled(self, default_settings):
        default_settings.discard_trailing_3_6 = False
        default_settings.save()
        assert services.is_discard_trailing_3_6_enabled() is False

    def test_record_wrong_punch_increments_per_event(
            self, default_settings, teller_user, active_event):
        first = services.record_wrong_punch(teller_user)
        second = services.record_wrong_punch(teller_user)
        assert first['count'] == 1
        assert second['count'] == 2
        assert second['event_name'] == active_event.name
        assert second['rank'] == 1
        assert second['tellers_counted'] == 1

    def test_record_wrong_punch_ranks_by_most(
            self, default_settings, teller_user, teller_user2, active_event):
        services.record_wrong_punch(teller_user)
        services.record_wrong_punch(teller_user)
        services.record_wrong_punch(teller_user)
        low = services.record_wrong_punch(teller_user2)
        assert low['count'] == 1
        assert low['rank'] == 2
        assert low['tellers_counted'] == 2
        assert services.get_wrong_punch_count(teller_user) == 3
        top = services.get_wrong_punch_stats(teller_user, event=active_event)
        assert top['rank'] == 1

    def test_record_wrong_punch_without_event_is_noop(self, default_settings, teller_user):
        result = services.record_wrong_punch(teller_user)
        assert result['count'] == 0
        assert result['event_name'] is None

    def test_leaderboard_most_punches_wins(
            self, default_settings, teller_user, teller_user2, active_event):
        from SmartWagers.models import Wagers
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=100,
            cashier=teller_user.username, registered=True,
        )
        Wagers.objects.create(
            fightnum=1, side='WALA', wager=100,
            cashier=teller_user2.username, registered=True,
        )
        services.record_wrong_punch(teller_user)
        services.record_wrong_punch(teller_user)
        services.record_wrong_punch(teller_user2)
        board = services.get_wrong_punch_leaderboard(active_event)
        assert board['has_contestants'] is True
        assert board['best_count'] == 2
        assert [w['username'] for w in board['winners']] == [teller_user.username]
