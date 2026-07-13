"""
Tests for the fight lifecycle service functions.

Covers: startnewmatch, closematch, cancelmatch, endmatch,
update_fight_status, get_fight_status, get_fightnum.
"""

import pytest
from SmartWagers.models import Fight_Status, Fight_Results, Totals, Wagers
from SmartWagers import services


# ---------------------------------------------------------------------------
# get_fightnum
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetFightnum:

    def test_returns_1_when_no_wagers(self):
        assert services.get_fightnum() == 1

    def test_returns_fightnum_of_latest_registered_wager(self):
        Wagers.objects.create(fightnum=3, side='START', wager=0, cashier='System', registered=True)
        assert services.get_fightnum() == 3

    def test_ignores_unregistered_wagers(self):
        """get_fightnum must read from registered=True wagers only."""
        Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
        # unregistered pending wager at a higher fight number must be ignored
        Wagers.objects.create(fightnum=5, side='MERON', wager=100, cashier='teller1', registered=False)
        assert services.get_fightnum() == 1

    def test_returns_fightnum_of_latest_not_first(self):
        Wagers.objects.create(fightnum=2, side='START', wager=0, cashier='System', registered=True)
        Wagers.objects.create(fightnum=3, side='START', wager=0, cashier='System', registered=True)
        assert services.get_fightnum() == 3


# ---------------------------------------------------------------------------
# get_fight_status
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetFightStatus:

    def test_creates_default_status_when_none_exists(self):
        overall, meron, wala, fn = services.get_fight_status()
        assert overall == 'CLOSE'
        assert Fight_Status.objects.count() == 1

    def test_returns_existing_status(self):
        Fight_Status.objects.create(
            fightnum=2, overall_status='OPEN', meron_status='OPEN', wala_status='OPEN'
        )
        overall, meron, wala, fn = services.get_fight_status()
        assert overall == 'OPEN'
        assert fn == 2


# ---------------------------------------------------------------------------
# startnewmatch
# ---------------------------------------------------------------------------

def _seed_event_anchor():
    """Simulate start_event() by placing a fightnum=0 System anchor wager.
    startnewmatch() reads get_fightnum() == 0 and then calls
    initialize_fightnum() to produce fight 1."""
    Wagers.objects.create(fightnum=0, side='EVENT_START', wager=0,
                           cashier='System', registered=True)
    Fight_Status.objects.all().delete()
    Fight_Status.objects.create(
        fightnum=0, overall_status='CLOSE',
        meron_status='CLOSE', wala_status='CLOSE',
    )
    Totals.objects.create(fightnum=0, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)


@pytest.mark.django_db
class TestStartNewMatch:

    def test_first_match_is_fight_1(self, default_settings):
        _seed_event_anchor()
        services.startnewmatch()
        assert services.get_fightnum() == 1

    def test_subsequent_match_increments_fightnum(self, default_settings):
        _seed_event_anchor()
        services.startnewmatch()
        services.closematch()
        services.endmatch('MERON')
        services.startnewmatch()
        assert services.get_fightnum() == 2

    def test_sets_overall_status_to_open(self, default_settings):
        _seed_event_anchor()
        services.startnewmatch()
        overall, meron, wala, _ = services.get_fight_status()
        assert overall == 'OPEN'

    def test_sets_both_sides_to_open(self, default_settings):
        _seed_event_anchor()
        services.startnewmatch()
        _, meron, wala, _ = services.get_fight_status()
        assert meron == 'OPEN'
        assert wala == 'OPEN'

    def test_resets_totals_to_zero(self, default_settings):
        _seed_event_anchor()
        Totals.objects.create(fightnum=0, mtotal=500, wtotal=300, mpayout=0, wpayout=0, totalpot=800)
        services.startnewmatch()
        m, _, w, _, pot, _ = services.get_Totals()
        assert m == 0
        assert w == 0
        assert pot == 0

    def test_creates_start_wager_marker(self, default_settings):
        _seed_event_anchor()
        services.startnewmatch()
        start_markers = Wagers.objects.filter(side='START')
        assert start_markers.exists()


# ---------------------------------------------------------------------------
# closematch
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCloseMatch:

    def test_overall_status_becomes_closed(self, default_settings):
        services.startnewmatch()
        services.closematch()
        overall, _, _, _ = services.get_fight_status()
        assert overall == 'CLOSED'

    def test_is_betting_open_returns_false_after_close(self, default_settings):
        services.startnewmatch()
        services.closematch()
        assert services.is_betting_open('MERON') is False
        assert services.is_betting_open('WALA') is False

    def test_is_match_open_returns_false_after_close(self, default_settings):
        services.startnewmatch()
        services.closematch()
        assert services.is_match_open() is False

    def test_side_statuses_become_close(self, default_settings):
        services.startnewmatch()
        services.closematch()
        _, meron, wala, _ = services.get_fight_status()
        assert meron == 'CLOSE'
        assert wala == 'CLOSE'


# ---------------------------------------------------------------------------
# cancelmatch
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCancelMatch:

    def test_archives_cancelled_fight_result(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        services.cancelmatch()
        result = Fight_Results.objects.filter(fightnum=fn, side='CANCELLED').first()
        assert result is not None

    def test_overall_status_becomes_cancelled(self, default_settings):
        services.startnewmatch()
        services.cancelmatch()
        overall, _, _, _ = services.get_fight_status()
        assert overall == 'CANCELLED'

    def test_fight_result_odds_is_cancelled(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        services.cancelmatch()
        result = Fight_Results.objects.filter(fightnum=fn).first()
        assert result.odds == 'CANCELLED'

    def test_totals_reset_after_cancel(self, default_settings):
        services.startnewmatch()
        services.cancelmatch()
        m, _, w, _, pot, _ = services.get_Totals()
        assert m == 0
        assert w == 0
        assert pot == 0


# ---------------------------------------------------------------------------
# endmatch
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEndMatch:

    def test_meron_win_archives_meron_result(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        # Place bets so payout is computable
        Totals.objects.create(fightnum=fn, mtotal=500, wtotal=300,
                               mpayout=0, wpayout=0, totalpot=800)
        services.endmatch('MERON')
        result = Fight_Results.objects.filter(fightnum=fn).first()
        assert result is not None
        assert result.side == 'MERON'

    def test_wala_win_archives_wala_result(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        Totals.objects.create(fightnum=fn, mtotal=300, wtotal=500,
                               mpayout=0, wpayout=0, totalpot=800)
        services.endmatch('WALA')
        result = Fight_Results.objects.filter(fightnum=fn).first()
        assert result.side == 'WALA'

    def test_overall_status_becomes_complete(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        Totals.objects.create(fightnum=fn, mtotal=500, wtotal=300,
                               mpayout=0, wpayout=0, totalpot=800)
        services.endmatch('MERON')
        overall, _, _, _ = services.get_fight_status()
        assert overall == 'COMPLETE'

    def test_totals_reset_after_end(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        Totals.objects.create(fightnum=fn, mtotal=500, wtotal=300,
                               mpayout=0, wpayout=0, totalpot=800)
        services.endmatch('MERON')
        m, _, w, _, pot, _ = services.get_Totals()
        assert m == 0 and w == 0 and pot == 0

    def test_draw_result_archives_draw(self, default_settings):
        services.startnewmatch()
        fn = services.get_fightnum()
        Totals.objects.create(fightnum=fn, mtotal=400, wtotal=400,
                               mpayout=0, wpayout=0, totalpot=800)
        services.endmatch('DRAW')
        result = Fight_Results.objects.filter(fightnum=fn).first()
        assert result.side == 'DRAW'


# ---------------------------------------------------------------------------
# update_fight_status — explicit status transitions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUpdateFightStatus:

    def test_start_sets_open(self):
        Fight_Status.objects.create(fightnum=0, overall_status='CLOSE',
                                    meron_status='CLOSE', wala_status='CLOSE')
        Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
        services.update_fight_status('START')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.overall_status == 'OPEN'

    def test_closed_transition(self):
        Fight_Status.objects.create(fightnum=1, overall_status='OPEN',
                                    meron_status='OPEN', wala_status='OPEN')
        Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
        services.update_fight_status('CLOSED', 'BOTH')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.overall_status == 'CLOSED'

    def test_cancel_transition(self):
        Fight_Status.objects.create(fightnum=1, overall_status='OPEN',
                                    meron_status='OPEN', wala_status='OPEN')
        Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
        services.update_fight_status('CANCEL')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.overall_status == 'CANCELLED'

    def test_end_transition(self):
        Fight_Status.objects.create(fightnum=1, overall_status='OPEN',
                                    meron_status='OPEN', wala_status='OPEN')
        Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
        services.update_fight_status('END')
        fs = Fight_Status.objects.order_by('id').first()
        assert fs.overall_status == 'COMPLETE'
