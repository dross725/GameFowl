import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from SmartWagers import operations_status


@pytest.mark.django_db
def test_liveness_stays_available_and_reports_version(client):
    response = client.get("/health/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["app_version"] == "1.14.0"
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_readiness_reports_failed_dependency(client, monkeypatch):
    monkeypatch.setattr(operations_status, "probe_database", lambda: {"ok": True})
    monkeypatch.setattr(operations_status, "probe_redis", lambda: {"ok": False, "detail": "down"})
    monkeypatch.setattr(operations_status, "probe_migrations", lambda: {"ok": True})
    monkeypatch.setattr(operations_status, "probe_master_lock", lambda: {"ok": True})
    monkeypatch.setattr(operations_status, "probe_release", lambda: {"ok": True})
    response = client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["ok"] is False


@pytest.mark.django_db
def test_operations_status_is_admin_only(client, admin_user, teller_user):
    denied = Client()
    denied.force_login(teller_user)
    assert denied.get("/operations/status/").status_code == 403

    allowed = Client()
    allowed.force_login(admin_user)
    response = allowed.get("/operations/status/")
    assert response.status_code == 200
    payload = response.json()
    assert "print_agent" in payload
    assert "backup" in payload
    encoded = json.dumps(payload)
    assert "SECRET" not in encoded
    assert User.objects.count() >= 2
