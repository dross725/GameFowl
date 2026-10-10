"""Liveness, readiness, and protected operations status.

Liveness only reports that the process can answer. Readiness checks the database,
Redis, migration state, master lock, and release metadata without returning secrets.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError


def _release_metadata():
    deploy_dir = Path(settings.BASE_DIR) / "deploy"
    if str(deploy_dir) not in sys.path:
        sys.path.insert(0, str(deploy_dir))
    import release_metadata

    return release_metadata


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def installed_version() -> str:
    path = Path(settings.BASE_DIR) / "VERSION"
    if not path.is_file():
        return "unknown"
    return path.read_text(encoding="utf-8").strip() or "unknown"


def release_document() -> dict:
    return read_json(Path(settings.BASE_DIR) / "deploy" / ".deployed_release.json")


def liveness_payload() -> dict:
    from . import masterlock

    status = masterlock.get_status(touch_heartbeat=False)
    release = release_document()
    return {
        "ok": True,
        "locked": bool(status.get("locked")),
        "enabled": bool(status.get("enabled")),
        "manual_locked": bool(status.get("manual_locked")),
        "lock_reasons": status.get("lock_reasons") or [],
        "valid_until": status.get("valid_until"),
        "app_version": release.get("app_version") or installed_version(),
        "commit_sha": release.get("commit_sha") or "",
        "schema_level": release.get("schema_level") or "",
    }


def probe_database() -> dict:
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        if row != (1,):
            return {"ok": False, "detail": "database probe returned an unexpected result"}
        return {"ok": True, "vendor": connection.vendor}
    except Exception:
        return {"ok": False, "detail": "database probe failed"}


def probe_redis() -> dict:
    host = getattr(settings, "REDIS_HOST", "127.0.0.1")
    port = int(getattr(settings, "REDIS_PORT", 6379))
    try:
        import redis

        client = redis.Redis(host=host, port=port, socket_connect_timeout=0.4, socket_timeout=0.4)
        if client.ping():
            return {"ok": True, "host": host, "port": port}
        return {"ok": False, "detail": "redis ping failed", "host": host, "port": port}
    except Exception:
        return {"ok": False, "detail": "redis probe failed", "host": host, "port": port}


def probe_migrations() -> dict:
    from django.db.migrations.recorder import MigrationRecorder

    release = release_document()
    expected = str(release.get("schema_level") or "")
    try:
        applied = [
            name
            for app, name in MigrationRecorder(connection).applied_migrations()
            if app == "SmartWagers"
        ]
    except Exception:
        return {"ok": False, "detail": "migration state could not be read", "expected": expected}
    latest = ""
    if applied:
        metadata = _release_metadata()
        latest = sorted(applied, key=metadata.migration_sort_key)[-1]
    if expected and latest and _release_metadata().migration_sort_key(latest) < _release_metadata().migration_sort_key(expected):
        return {
            "ok": False,
            "detail": "database schema is behind the deployed release",
            "applied": latest,
            "expected": expected,
        }
    return {"ok": True, "applied": latest, "expected": expected}


def probe_master_lock() -> dict:
    from . import masterlock

    try:
        status = masterlock.get_status(touch_heartbeat=False)
    except Exception:
        return {"ok": False, "detail": "master lock state is unreadable"}
    if status.get("error"):
        return {"ok": False, "detail": "master lock state is invalid"}
    return {
        "ok": True,
        "locked": bool(status.get("locked")),
        "enabled": bool(status.get("enabled")),
    }


def probe_release() -> dict:
    document = release_document()
    if not document:
        return {"ok": True, "detail": "no deployed release metadata yet", "app_version": installed_version()}
    if not document.get("commit_sha") and not document.get("app_version"):
        return {"ok": False, "detail": "release metadata is incomplete"}
    return {
        "ok": True,
        "app_version": document.get("app_version") or installed_version(),
        "schema_level": document.get("schema_level") or "",
    }


def readiness_payload() -> tuple[bool, dict]:
    checks = {
        "database": probe_database(),
        "redis": probe_redis(),
        "migrations": probe_migrations(),
        "master_lock": probe_master_lock(),
        "release": probe_release(),
    }
    ok = all(bool(item.get("ok")) for item in checks.values())
    release = release_document()
    return ok, {
        "ok": ok,
        "app_version": release.get("app_version") or installed_version(),
        "commit_sha": release.get("commit_sha") or "",
        "schema_level": release.get("schema_level") or "",
        "checks": checks,
    }


def _backup_status() -> dict:
    configured = getattr(settings, "BACKUP_STATUS_PATH", "")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(settings.BASE_DIR).parent / "backups" / "last_backup.json")
    for path in candidates:
        document = read_json(path)
        if document:
            return {
                "created_at": document.get("created_at"),
                "validated": document.get("validated"),
                "bytes": document.get("bytes"),
                "path_recorded": bool(document.get("path")),
            }
    return {"created_at": None, "validated": None, "bytes": None, "path_recorded": False}


def _pending_email_count() -> int | None:
    try:
        from .models import EventReportEmail

        return EventReportEmail.objects.filter(
            status__in=(
                EventReportEmail.STATUS_PENDING,
                EventReportEmail.STATUS_FAILED,
                EventReportEmail.STATUS_SENDING,
            )
        ).count()
    except (OperationalError, Exception):
        return None


def _print_agents() -> dict:
    metadata = _release_metadata()
    release = release_document()
    minimum = str(release.get("print_agent_min_version") or metadata.PRINT_AGENT_MIN_VERSION)
    reports_path = Path(settings.BASE_DIR) / "deploy" / "teller_agent_reports.json"
    document = read_json(reports_path)
    reports = document.get("agents") if isinstance(document.get("agents"), list) else []
    bundled = metadata.read_print_agent_version(Path(settings.BASE_DIR))
    return {
        "bundled_version": bundled,
        "minimum_version": minimum,
        "outdated": metadata.outdated_agents(reports, minimum),
    }


def operations_payload() -> dict:
    ready, readiness = readiness_payload()
    usage = shutil.disk_usage(Path(settings.BASE_DIR))
    return {
        "ok": ready,
        "readiness": readiness,
        "backup": _backup_status(),
        "pending_event_emails": _pending_email_count(),
        "print_agent": _print_agents(),
        "disk_free_bytes": usage.free,
        "service": "process-up",
    }
