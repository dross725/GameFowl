"""
Tests for SmartWagers HTTP views.

Covers: RoleBasedLoginView redirects, group guards, JSON API responses,
admin action POST guards, and teller transaction view.
"""

import json
import pytest
from django.test import Client
from SmartWagers.models import (
    Event, Fight_Status, Settings, TellerTransaction, Totals, Wagers,
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

    def test_admin_accessing_teller_page_gets_403(self, admin_user):
        client = Client()
        client.force_login(admin_user)
        response = client.get('/user')
        assert response.status_code == 403

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

    def test_get_fight_status_returns_json(self):
        _open_fight()
        client = Client()
        response = client.get('/get_fight_status_view/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'overall_status' in data
        assert 'meron_status' in data
        assert 'wala_status' in data
        assert 'fightnum' in data

    def test_get_pot_values_returns_json(self, default_settings):
        Totals.objects.create(fightnum=1, mtotal=500, wtotal=300, mpayout=90, wpayout=150, totalpot=800)
        client = Client()
        response = client.get('/get_pot_values/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'M_total_bet' in data
        assert 'W_total_bet' in data
        assert data['M_total_bet'] == 500

    def test_get_button_state_returns_mstate_and_wstate(self, default_settings):
        client = Client()
        response = client.get('/get_button_state_view/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'mstate' in data
        assert 'wstate' in data

    def test_get_fight_results_returns_list(self):
        client = Client()
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

    def test_start_event_post_creates_event(self, admin_user, default_settings):
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/start-event/', {'event_name': 'Night Derby'})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data.get('ok') is True
        assert Event.objects.filter(is_active=True).exists()

    def test_end_event_post_ends_active_event(self, admin_user, active_event):
        client = Client()
        client.force_login(admin_user)
        response = client.post('/administrator/end-event/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data.get('ok') is True
        active_event.refresh_from_db()
        assert active_event.is_active is False


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


# ---------------------------------------------------------------------------
# teller_transaction (REMIT)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTellerTransactionView:

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

    def test_valid_remit_creates_transaction(self, teller_user, default_settings):
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

    def test_remit_response_contains_updated_balance(self, teller_user, default_settings):
        client = Client()
        client.force_login(teller_user)
        response = client.post('/teller_transaction/', {
            'transaction_type': 'REMIT', 'amount': '500',
        })
        data = json.loads(response.content)
        assert 'balance' in data
        assert 'transaction_id' in data
