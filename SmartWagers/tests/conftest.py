"""
Shared pytest fixtures for the SmartWagers test suite.

Every fixture that creates DB rows uses Django's standard transaction isolation
so each test starts with a clean slate (Django rolls back after each test when
using pytest-django's @pytest.mark.django_db decorator).
"""

import pytest
from django.contrib.auth.models import User, Group
from SmartWagers.models import (
    Event, Fight_Status, Settings, TellerStatus, Totals, Wagers,
)


# ---------------------------------------------------------------------------
# User / group fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_group(db):
    group, _ = Group.objects.get_or_create(name='admin')
    return group


@pytest.fixture
def teller_group(db):
    group, _ = Group.objects.get_or_create(name='teller')
    return group


@pytest.fixture
def display_group(db):
    group, _ = Group.objects.get_or_create(name='display')
    return group


@pytest.fixture
def admin_user(db, admin_group):
    user = User.objects.create_user(
        username='testadmin', password='adminpass123',
        first_name='Test', last_name='Admin',
    )
    user.groups.add(admin_group)
    return user


@pytest.fixture
def teller_user(db, teller_group):
    user = User.objects.create_user(
        username='testteller', password='tellerpass123',
        first_name='Test', last_name='Teller',
    )
    user.groups.add(teller_group)
    return user


@pytest.fixture
def teller_user2(db, teller_group):
    """A second teller — used for cross-teller guard tests."""
    user = User.objects.create_user(
        username='testteller2', password='tellerpass123',
        first_name='Test', last_name='Teller2',
    )
    user.groups.add(teller_group)
    return user


@pytest.fixture
def display_user(db, display_group):
    user = User.objects.create_user(
        username='testdisplay', password='displaypass123',
    )
    user.groups.add(display_group)
    return user


# ---------------------------------------------------------------------------
# Settings / config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_settings(db):
    """A single Settings row with known plasada and teller fund limits."""
    return Settings.objects.create(
        plasada=0.05,
        M_control_status='OPEN',
        W_control_status='OPEN',
        teller_max_balance=50000.0,
        teller_initial_fund=10000.0,
        teller_min_balance=1000.0,
    )


# ---------------------------------------------------------------------------
# Event fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def active_event(db):
    """A live Event with is_active=True."""
    return Event.objects.create(name='Test Event 1', is_active=True)


# ---------------------------------------------------------------------------
# Fight state fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def open_fight(db):
    """Fight_Status in OPEN state at fight number 1, with a seed Totals row."""
    fs = Fight_Status.objects.create(
        fightnum=1,
        overall_status='OPEN',
        meron_status='OPEN',
        wala_status='OPEN',
    )
    Totals.objects.create(fightnum=1, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
    # Seed a registered system wager so get_fightnum() returns 1
    Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
    return fs


@pytest.fixture
def closed_fight(db):
    """Fight_Status in CLOSED state at fight number 1."""
    fs = Fight_Status.objects.create(
        fightnum=1,
        overall_status='CLOSED',
        meron_status='CLOSE',
        wala_status='CLOSE',
    )
    Totals.objects.create(fightnum=1, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
    Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System', registered=True)
    return fs


# ---------------------------------------------------------------------------
# TellerStatus fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def teller_status_online(db, teller_user):
    """TellerStatus(is_online=True) for the default teller user."""
    status, _ = TellerStatus.objects.get_or_create(user=teller_user, defaults={'is_online': True})
    status.is_online = True
    status.save()
    return status


@pytest.fixture
def teller_status_offline(db, teller_user):
    """TellerStatus(is_online=False) for the default teller user."""
    status, _ = TellerStatus.objects.get_or_create(user=teller_user, defaults={'is_online': False})
    status.is_online = False
    status.save()
    return status
