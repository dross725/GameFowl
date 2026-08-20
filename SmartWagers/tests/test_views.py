"""
Tests for SmartWagers HTTP views.

Covers: RoleBasedLoginView redirects, group guards, JSON API responses,
admin action POST guards, and teller transaction view.
"""

import json
import pytest
from django.test import Client
from SmartWagers.models import (
    Event, Fight_Status, Settings, TellerStatus, TellerTransaction, Totals,
    Wagers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_fight(fightnum=1):
    Fight_Status.objects.all().delete()
    Fight_Status.objects.create(
        fightnum=fightnum, overall_status='OPEN',
        meron_status='OPEN', wala_status='OPEN',
    )
    Totals.objects.create(fightnum=fightnum, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
    Wagers.objects.create(fightnum=fightnum, side='START', wager=0, cashier='System', registered=True)


# ---------------------------------------------------------------------------
# Authentication / login redirects
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRoleBasedLoginView:

    def test_admin_redirected_to_administrator(self, admin_user):
        client = Client()
        response = client.post('/login', {
            'username': admin_user.username,
            'password': 'adminpass123',
        })
        assert response.status_code in (301, 302)
        assert '/administrator' in response['Location']

    def test_teller_redirected_to_user(self, teller_user):
        client = Client()
        response = client.post('/login', {
            'username': teller_user.username,
            'password': 'tellerpass123',
        })
        assert response.status_code in (301, 302)
        assert '/user' in response['Location']

    def test_display_redirected_to_index(self, display_user):
        client = Client()
        response = client.post('/login', {
            'username': display_user.username,
            'password': 'displaypass123',
        })
        assert response.status_code in (301, 302)
        assert 'index' in response['Location'] or response['Location'] == '/'

    def test_wrong_password_returns_200_with_error(self):
        client = Client()
        response = client.post('/login', {
            'username': 'nobody',
            'password': 'wrongpassword',
        })
        assert response.status_code == 200

    def test_unauthenticated_get_returns_login_form(self):
        client = Client()
        response = client.get('/login')
        assert response.status_code == 200

    def test_authenticated_teller_visiting_login_goes_to_user(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/login')
        assert response.status_code in (301, 302)
        assert '/user' in response['Location']

    def test_teller_login_ignores_next_admin(self, teller_user):
        client = Client()
        response = client.post('/login?next=/administrator', {
            'username': teller_user.username,
            'password': 'tellerpass123',
        })
        assert response.status_code in (301, 302)
        assert '/user' in response['Location']
        assert '/administrator' not in response['Location']


# ---------------------------------------------------------------------------
# Group guards
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupGuards:

    def test_unauthenticated_admin_page_redirects_to_login(self):
        client = Client()
        response = client.get('/administrator')
        assert response.status_code in (301, 302)
        assert 'login' in response['Location'].lower()

    def test_teller_accessing_admin_page_gets_403(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/administrator')
        assert response.status_code == 403
        assert b'Access Denied' in response.content

    def test_teller_accessing_index_gets_403(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/')
        assert response.status_code == 403
        assert b'Access Denied' in response.content

    def test_admin_accessing_teller_page_gets_403(self, admin_user):
        client = Client()
        client.force_login(admin_user)
        response = client.get('/user')
        assert response.status_code == 403
        assert b'Access Denied' in response.content

    def test_unauthenticated_teller_page_redirects_to_login(self):
        client = Client()
        response = client.get('/user')
        assert response.status_code in (301, 302)
        assert 'login' in response['Location'].lower()

    def test_admin_can_access_admin_page(self, admin_user, default_settings):
        _open_fight()
        client = Client()
        client.force_login(admin_user)
        response = client.get('/administrator')
        assert response.status_code == 200

    def test_teller_can_access_teller_page(self, teller_user, default_settings):
        _open_fight()
        client = Client()
        client.force_login(teller_user)
        response = client.get('/user')
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestJsonApiEndpoints:

    def test_get_fight_status_returns_json(self, teller_user):
        _open_fight()
        client = Client()
        client.force_login(teller_user)
        response = client.get('/get_fight_status_view/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'overall_status' in data
        assert 'meron_status' in data
        assert 'wala_status' in data
        assert 'fightnum' in data

    def test_get_pot_values_returns_json(self, default_settings, teller_user):
        Totals.objects.create(fightnum=1, mtotal=500, wtotal=300, mpayout=90, wpayout=150, totalpot=800)
        client = Client()
        client.force_login(teller_user)
        response = client.get('/get_pot_values/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'M_total_bet' in data
        assert 'W_total_bet' in data
        assert data['M_total_bet'] == 500

    def test_get_button_state_returns_mstate_and_wstate(self, default_settings, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/get_button_state_view/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'mstate' in data
        assert 'wstate' in data

    def test_get_fight_results_returns_list(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/get_fight_results_view/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert isinstance(data, list)

    def test_get_teller_balance_requires_auth(self):
        client = Client()
        response = client.get('/get_teller_balance/')
        assert response.status_code in (301, 302)

    def test_get_teller_balance_returns_balance_for_teller(
            self, teller_user, default_settings, active_event):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/get_teller_balance/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'balance' in data
        assert data['ok'] is True

    def test_dual_role_admin_sees_shared_admin_balance_on_teller_page(
            self, admin_user, teller_group, default_settings, active_event):
        admin_user.groups.add(teller_group)
        client = Client()
        client.force_login(admin_user)

        response = client.get('/get_teller_balance/')

        assert response.status_code == 200
        data = response.json()
        assert data['balance'] == 100000
        assert data['shared_admin_fund'] is True


# ---------------------------------------------------------------------------
# Admin action POST guards
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminActionGuards:

    def test_start_event_get_returns_405(self, admin_user):
        client = Client()
        client.force_login(admin_user)
        response = client.get('/administrator/start-event/')
        assert response.status_code == 405

    def test_end_event_get_returns_405(self, admin_user):
        client = Client()
        client.force_login(admin_user)
        response = client.get('/administrator/end-event/')
        assert response.status_code == 405

    def test_start_event_requires_admin_group(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/administrator/start-event/', {'name': 'Test'})
        assert response.status_code == 403
        assert Event.objects.count() == 0

    def test_start_event_post_creates_event(self, admin_user, default_settings):
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/start-event/', {'event_name': 'Night Derby'})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data.get('ok') is True
        assert Event.objects.filter(is_active=True).exists()

    def test_admin_can_update_admin_initial_fund(
            self, admin_user, default_settings):
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/settings/', {
            'action': 'update_admin_initial_fund',
            'admin_initial_fund': '125000',
        })
        assert response.status_code == 200
        assert response.json() == {
            'ok': True,
            'admin_initial_fund': 125000.0,
        }
        default_settings.refresh_from_db()
        assert default_settings.admin_initial_fund == 125000.0

    def test_end_event_post_ends_active_event(self, admin_user, active_event):
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/end-event/', {
            'actual_admin_cash': '99,950.25',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data.get('ok') is True
        active_event.refresh_from_db()
        assert active_event.is_active is False
        assert active_event.actual_admin_cash_counted == 99950.25
        assert active_event.admin_cash_counted_by == admin_user

    def test_end_event_requires_valid_admin_cash(self, admin_user, active_event):
        client = Client()
        client.force_login(admin_user)

        response = client.post('/administrator/end-event/')

        assert response.status_code == 400
        assert response.json()['error'] == 'invalid_actual_admin_cash'
        active_event.refresh_from_db()
        assert active_event.is_active is True


# ---------------------------------------------------------------------------
# reprint_wager
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReprintWager:

    def test_get_returns_405(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/reprint_wager/')
        assert response.status_code == 405

    def test_missing_transaction_id_returns_400(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/reprint_wager/', {})
        assert response.status_code == 400

    def test_nonexistent_transaction_returns_not_found(self, teller_user, active_event):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/reprint_wager/', {'transaction_id': '999999'})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is False

    def test_test_keyword_returns_printer_test_receipt(self, teller_user, active_event):
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=250,
            cashier=teller_user.username, registered=True,
        )
        client = Client()
        client.force_login(teller_user)

        response = client.post('/reprint_wager/', {'transaction_id': 'TEST'})

        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['receipt_type'] == 'test'
        assert data['receipt']['receipt_type'] == 'wager'
        assert data['receipt']['test_print'] is True
        assert data['receipt']['transaction_id'] == 'test'
        assert data['receipt']['cashier'] == teller_user.username
        assert data['receipt']['amount'] == 250

    def test_valid_transaction_returns_receipt(self, teller_user, active_event):
        w = Wagers.objects.create(
            fightnum=1, side='MERON', wager=300,
            cashier=teller_user.username, registered=True,
        )
        client = Client()
        client.force_login(teller_user)
        response = client.post('/reprint_wager/', {'transaction_id': w.transactionid})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert 'receipt' in data

    def test_unpadded_transaction_id_still_finds_ticket(self, teller_user, active_event):
        w = Wagers.objects.create(
            fightnum=1, side='MERON', wager=300,
            cashier=teller_user.username, registered=True,
        )
        assert w.transactionid.startswith('0')
        client = Client()
        client.force_login(teller_user)
        response = client.post(
            '/reprint_wager/',
            {'transaction_id': str(int(w.transactionid))},
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert data['receipt']['transaction_id'] == w.transactionid

    def test_teller_cannot_reprint_other_cashiers_ticket(
        self, teller_user, teller_user2, active_event,
    ):
        w = Wagers.objects.create(
            fightnum=1, side='MERON', wager=300,
            cashier=teller_user.username, registered=True,
        )
        client = Client()
        client.force_login(teller_user2)
        response = client.post('/reprint_wager/', {'transaction_id': w.transactionid})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is False
        assert data['error'] == 'notfound'

    def test_admin_can_reprint_any_ticket(
        self, admin_user, teller_user, active_event,
    ):
        w = Wagers.objects.create(
            fightnum=1, side='WALA', wager=200,
            cashier=teller_user.username, registered=True,
        )
        client = Client()
        client.force_login(admin_user)
        response = client.post('/reprint_wager/', {'transaction_id': w.transactionid})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True

    def test_remit_transaction_returns_remit_receipt(
        self, teller_user, active_event,
    ):
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=5000,
        )
        remit = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=500,
        )
        client = Client()
        client.force_login(teller_user)
        response = client.post('/reprint_wager/', {'transaction_id': remit.transaction_id})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert data['receipt_type'] == 'remit'
        assert data['receipt']['transaction_id'] == remit.transaction_id
        assert data['receipt']['transaction_type'] == 'REMIT'
        assert data['receipt']['amount'] == 500

    def test_unpadded_remit_id_still_finds_receipt(
        self, teller_user, active_event,
    ):
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=5000,
        )
        remit = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=250,
        )
        # Strip leading zeros after R, e.g. R000007 -> R7
        short_id = 'R' + str(int(remit.transaction_id[1:]))
        client = Client()
        client.force_login(teller_user)
        response = client.post('/reprint_wager/', {'transaction_id': short_id})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert data['receipt_type'] == 'remit'
        assert data['receipt']['transaction_id'] == remit.transaction_id

    def test_teller_cannot_reprint_other_tellers_remit(
        self, teller_user, teller_user2, active_event,
    ):
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=5000,
        )
        remit = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=100,
        )
        client = Client()
        client.force_login(teller_user2)
        response = client.post('/reprint_wager/', {'transaction_id': remit.transaction_id})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is False
        assert data['error'] == 'notfound'

    def test_collect_transaction_is_not_reprintable(
        self, teller_user, active_event,
    ):
        collect = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=1000,
        )
        client = Client()
        client.force_login(teller_user)
        response = client.post('/reprint_wager/', {'transaction_id': collect.transaction_id})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is False
        assert data['error'] == 'notfound'


# ---------------------------------------------------------------------------
# teller_transaction (REMIT)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTellerTransactionView:

    def _seed_cash_on_hand(self, teller_user, amount=5000):
        """Give the teller cash on hand via a COLLECT (borrow) so remits can succeed."""
        return TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=amount,
        )

    def test_get_returns_405(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.get('/teller_transaction/')
        assert response.status_code == 405

    def test_non_remit_type_returns_400(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'COLLECT', 'amount': '500',
        })
        assert response.status_code == 400

    def test_invalid_amount_returns_400(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': 'notanumber',
        })
        assert response.status_code == 400

    def test_zero_amount_returns_400(self, teller_user):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '0',
        })
        assert response.status_code == 400

    def test_remit_exceeding_cash_on_hand_returns_400(self, teller_user, default_settings):
        self._seed_cash_on_hand(teller_user, amount=1000)
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '1000.01',
        })
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['ok'] is False
        assert data['error'] == 'exceeds_cash_on_hand'
        assert data['balance'] == 1000
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type='REMIT'
        ).exists()

    def test_remit_with_zero_cash_on_hand_returns_400(self, teller_user, default_settings):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '100',
        })
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['error'] == 'exceeds_cash_on_hand'
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type='REMIT'
        ).exists()

    def test_valid_remit_creates_transaction(self, teller_user, default_settings):
        self._seed_cash_on_hand(teller_user, amount=5000)
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '1000',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert TellerTransaction.objects.filter(
            user=teller_user, transaction_type='REMIT', amount=1000
        ).exists()

    def test_remit_equal_to_cash_on_hand_succeeds(self, teller_user, default_settings):
        self._seed_cash_on_hand(teller_user, amount=1500)
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '1500',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert data['balance'] == 0

    def test_remit_response_contains_updated_balance(self, teller_user, default_settings):
        self._seed_cash_on_hand(teller_user, amount=5000)
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '500',
        })
        data = json.loads(response.content)
        assert 'balance' in data
        assert 'transaction_id' in data
        assert data['balance'] == 4500

    def test_sequential_remits_second_fails_when_cash_exhausted(
        self, teller_user, default_settings,
    ):
        """Logic test: after remitting all cash, a second remit must fail."""
        self._seed_cash_on_hand(teller_user, amount=1000)
        client = Client()
        client.force_login(teller_user)
        first = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '1000',
        })
        assert first.status_code == 200
        second = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '1',
        })
        assert second.status_code == 400
        data = json.loads(second.content)
        assert data['error'] == 'exceeds_cash_on_hand'
        assert TellerTransaction.objects.filter(
            user=teller_user, transaction_type='REMIT',
        ).count() == 1


# ---------------------------------------------------------------------------
# admin_teller_txn (REMIT / COLLECT)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminTellerTxnView:

    def _seed_cash_on_hand(self, teller_user, amount=5000):
        return TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
            amount=amount,
        )

    def test_admin_remit_exceeding_cash_on_hand_returns_400(
        self, admin_user, teller_user, default_settings,
    ):
        self._seed_cash_on_hand(teller_user, amount=800)
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/teller-txn/', {
            'teller_id': teller_user.pk,
            'transaction_type': 'REMIT',
            'amount': '801',
        })
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['error'] == 'exceeds_cash_on_hand'
        assert not TellerTransaction.objects.filter(
            user=teller_user, transaction_type='REMIT'
        ).exists()

    def test_admin_remit_within_cash_on_hand_succeeds(
        self, admin_user, teller_user, default_settings, active_event,
    ):
        self._seed_cash_on_hand(teller_user, amount=800)
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/teller-txn/', {
            'teller_id': teller_user.pk,
            'transaction_type': 'REMIT',
            'amount': '800',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert data['balance'] == 0
        assert data['admin_fund_balance'] == 100000
        remit = TellerTransaction.objects.get(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
        )
        assert remit.received is True

    def test_admin_collect_uses_shared_admin_fund(
        self, admin_user, teller_user, default_settings, active_event,
    ):
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/teller-txn/', {
            'teller_id': teller_user.pk,
            'transaction_type': 'COLLECT',
            'amount': '5000',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['ok'] is True
        assert data['balance'] == 5000
        assert data['admin_fund_balance'] == 95000

    def test_admin_collect_rejected_when_shared_fund_is_insufficient(
        self, admin_user, teller_user, default_settings, active_event,
    ):
        active_event.admin_opening_fund = 1000
        active_event.save(update_fields=['admin_opening_fund'])
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/teller-txn/', {
            'teller_id': teller_user.pk,
            'transaction_type': 'COLLECT',
            'amount': '1001',
        })
        assert response.status_code == 400
        assert response.json()['error'] == 'exceeds_admin_fund'
        assert not TellerTransaction.objects.filter(
            user=teller_user,
            transaction_type=TellerTransaction.COLLECT,
        ).exists()

    def test_admin_cannot_issue_teller_borrow_to_dual_role_user(
            self, admin_user, teller_user, admin_group, active_event):
        teller_user.groups.add(admin_group)
        client = Client()
        client.force_login(admin_user)

        response = client.post('/administrator/teller-txn/', {
            'teller_id': teller_user.pk,
            'transaction_type': 'COLLECT',
            'amount': '5000',
        })

        assert response.status_code == 404
        assert response.json()['error'] == 'teller_not_found'
        assert not TellerTransaction.objects.filter(user=teller_user).exists()


# ---------------------------------------------------------------------------
# shared admin fund / bank
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminFundViews:

    def test_status_returns_shared_event_balance(
            self, admin_user, active_event):
        client = Client()
        client.force_login(admin_user)
        response = client.get('/administrator/fund/')
        assert response.status_code == 200
        data = response.json()
        assert data['active'] is True
        assert data['balance'] == 100000
        assert data['bank_borrowed'] == 100000

    def test_admin_can_borrow_from_and_remit_to_bank(
            self, admin_user, active_event):
        client = Client()
        client.force_login(admin_user)

        borrow = client.post('/administrator/fund/bank-transaction/', {
            'transaction_type': 'BORROW',
            'amount': '25000',
        })
        assert borrow.status_code == 200
        borrow_data = borrow.json()
        assert borrow_data['balance'] == 125000
        assert borrow_data['created_transaction']['transaction_type'] == 'BORROW'
        assert borrow_data['created_transaction']['transaction_id'].startswith('B')
        assert borrow_data['created_transaction']['amount'] == 25000
        assert borrow_data['print_required'] is True

        remit = client.post('/administrator/fund/bank-transaction/', {
            'transaction_type': 'REMIT',
            'amount': '5000',
        })
        assert remit.status_code == 200
        remit_data = remit.json()
        assert remit_data['balance'] == 120000
        assert remit_data['bank_borrowed'] == 125000
        assert remit_data['bank_remitted'] == 5000
        assert remit_data['net_bank_funding'] == 120000
        assert remit_data['created_transaction']['transaction_type'] == 'REMIT'
        assert remit_data['created_transaction']['amount'] == 5000

    def test_bank_remit_cannot_exceed_shared_balance(
            self, admin_user, active_event):
        client = Client()
        client.force_login(admin_user)
        response = client.post(
            '/administrator/fund/bank-transaction/',
            {'transaction_type': 'REMIT', 'amount': '100001'},
        )
        assert response.status_code == 400
        assert response.json()['error'] == 'exceeds_admin_fund'

    def test_bank_transaction_requires_active_event(self, admin_user):
        client = Client()
        client.force_login(admin_user)
        response = client.post(
            '/administrator/fund/bank-transaction/',
            {'transaction_type': 'BORROW', 'amount': '1000'},
        )
        assert response.status_code == 409
        assert response.json()['error'] == 'no_active_event'

    def test_teller_cannot_use_bank_endpoint(
            self, teller_user, active_event):
        client = Client()
        client.force_login(teller_user)
        response = client.post(
            '/administrator/fund/bank-transaction/',
            {'transaction_type': 'BORROW', 'amount': '1000'},
        )
        assert response.status_code == 403

    def test_remit_increases_pool_only_when_marked_received(
            self, admin_user, teller_user, active_event):
        txn = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=500,
        )
        client = Client()
        client.force_login(admin_user)

        before = client.get('/administrator/fund/').json()
        assert before['balance'] == 100000

        response = client.post('/administrator/mark-received/', {
            'transaction_id': txn.transaction_id,
        })
        assert response.status_code == 200
        assert response.json()['admin_fund_balance'] == 100500


# ---------------------------------------------------------------------------
# pre-event teller preparation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPreEventTellerPreparation:

    def test_tellers_page_excludes_users_who_are_also_admins(
            self, admin_user, teller_user, teller_user2, admin_group):
        teller_user.groups.add(admin_group)
        client = Client()
        client.force_login(admin_user)

        response = client.get('/administrator/tellers/')

        visible_ids = {
            item['user'].pk for item in response.context['teller_data']
        }
        assert teller_user.pk not in visible_ids
        assert teller_user2.pk in visible_ids

    def test_tellers_page_available_without_active_event(
            self, admin_user, teller_user, default_settings):
        TellerStatus.objects.create(user=teller_user, is_online=True)
        client = Client()
        client.force_login(admin_user)

        response = client.get('/administrator/tellers/')

        assert response.status_code == 200
        assert response.context['active_event'] is None
        assert response.context['online_teller_count'] == 1
        assert response.context['planned_teller_funds'] == 10000
        assert response.context['planned_bank_funds'] == 110000
        assert b'pre-event-funding' in response.content

    def test_online_status_can_be_set_without_issuing_funds(
            self, admin_user, teller_user, default_settings):
        status = TellerStatus.objects.create(
            user=teller_user,
            is_online=False,
        )
        client = Client()
        client.force_login(admin_user)

        response = client.post(
            '/administrator/teller-online-toggle/',
            {'teller_id': teller_user.pk, 'is_online': 'true'},
        )

        assert response.status_code == 200
        assert response.json()['fund_issued'] is False
        status.refresh_from_db()
        assert status.is_online is True
        assert not TellerTransaction.objects.filter(user=teller_user).exists()