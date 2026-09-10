"""Tests for shared ESC/POS builders and the mobile print queue."""
import base64

import pytest
from django.contrib.auth.models import Group, User

from SmartWagers import escpos_receipts
from SmartWagers.models import PrintDevice, PrintJob
from SmartWagers.print_queue import enqueue_print_job


@pytest.fixture
def teller_user(db):
    user = User.objects.create_user(username='teller1', password='pass12345')
    group, _ = Group.objects.get_or_create(name='teller')
    user.groups.add(group)
    return user


def test_escpos_wager_contains_title_and_barcode():
    payload = escpos_receipts.escpos_receipt({
        'receipt_type': 'wager',
        'transaction_id': '42',
        'event_name': 'Sunday Derby',
        'side': 'MERON',
        'amount': 100,
        'fightnum': 3,
        'cashier': 'teller1',
        'date': '2026-09-10 12:00:00',
    })
    assert b'BET RECEIPT' in payload
    assert b'MERON' in payload
    assert b'000042' in payload
    assert b'\x1dk\x49' in payload  # CODE128


def test_escpos_remit_dual_copies():
    payload = escpos_receipts.escpos_remit_receipt({
        'transaction_type': 'REMIT',
        'transaction_id': 'R123',
        'amount': 100,
        'balance': 500,
        'cashier': 'Teller One',
    })
    assert payload.count(b'TELLERS COPY') == 1
    assert payload.count(b'ADMIN COPY') == 1
    # Blank feed + cut between copies so they are separable on paper.
    teller_at = payload.index(b'TELLERS COPY')
    admin_at = payload.index(b'ADMIN COPY')
    between = payload[teller_at:admin_at]
    assert b'\n\n\n\n' in between
    assert b'\x1dV\x42\x04' in between


def test_enqueue_print_job_renders_bytes(teller_user):
    job = enqueue_print_job(
        teller_user,
        {
            'receipt_type': 'wager',
            'transaction_id': '7',
            'side': 'WALA',
            'amount': '50.00',
            'fightnum': 1,
            'cashier': 'teller1',
            'date': '2026-09-10',
        },
        endpoint='wager',
    )
    assert job.status == PrintJob.STATUS_PENDING
    assert job.transaction_id == '000007'
    assert b'BET RECEIPT' in bytes(job.escpos_bytes)


@pytest.mark.django_db
def test_print_device_login_and_pending_flow(client, teller_user):
    login_resp = client.post(
        '/api/print-devices/login/',
        data={
            'username': 'teller1',
            'password': 'pass12345',
            'device_id': 'device-abc',
            'platform': 'android',
        },
        content_type='application/json',
    )
    assert login_resp.status_code == 200
    token = login_resp.json()['token']

    client.force_login(teller_user)
    enqueue_resp = client.post(
        '/api/print-jobs/',
        data={
            'endpoint': 'wager',
            'receipt': {
                'receipt_type': 'wager',
                'transaction_id': '9',
                'side': 'MERON',
                'amount': 25,
                'fightnum': 2,
                'cashier': 'teller1',
                'date': '2026-09-10',
            },
        },
        content_type='application/json',
    )
    assert enqueue_resp.status_code == 200
    job_id = enqueue_resp.json()['job_id']

    pending = client.get(
        '/api/print-jobs/pending/',
        HTTP_AUTHORIZATION=f'Bearer {token}',
    )
    assert pending.status_code == 200
    jobs = pending.json()['jobs']
    assert len(jobs) == 1
    assert jobs[0]['id'] == job_id
    assert base64.b64decode(jobs[0]['escpos_base64'])

    ack = client.post(
        f'/api/print-jobs/{job_id}/ack/',
        data={'status': 'printed'},
        content_type='application/json',
        HTTP_AUTHORIZATION=f'Bearer {token}',
    )
    assert ack.status_code == 200
    assert PrintJob.objects.get(pk=job_id).status == PrintJob.STATUS_PRINTED
