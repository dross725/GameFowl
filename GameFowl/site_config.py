"""Environment-driven site settings shared by Django and deploy preflight.

This module must not import Django settings. Production fails closed when
required values are missing instead of accepting historical LAN addresses.
"""

from __future__ import annotations

from pathlib import Path


class SiteConfigError(RuntimeError):
    """Raised when production configuration is incomplete."""


DEV_HOSTS = ("localhost", "127.0.0.1")
DEV_CSRF_ORIGINS = ("http://localhost", "http://127.0.0.1", "http://localhost:8080", "http://127.0.0.1:8080")
INSECURE_SECRET_PREFIX = "django-insecure-"


def csv_values(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def resolve_csv(debug: bool, raw: str, name: str, dev_default: tuple[str, ...]) -> list[str]:
    values = csv_values(raw)
    if values:
        return values
    if debug:
        return list(dev_default)
    raise SiteConfigError(
        f"{name} must be set when DJANGO_DEBUG is false. "
        "Historical LAN addresses are not used as a fallback."
    )


def resolve_bool(raw: str | None, default: bool) -> bool:
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def email_settings(environ: dict[str, str], base_dir: Path) -> dict[str, object]:
    """SMTP settings. The password may come from the environment or .email_password."""
    host = environ.get("EMAIL_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    user = environ.get("EMAIL_HOST_USER", "atsportsclub1980@gmail.com").strip()
    password = environ.get("EMAIL_HOST_PASSWORD", "")
    if not password:
        password_path = base_dir / ".email_password"
        if password_path.is_file():
            password = password_path.read_text(encoding="utf-8").strip()
    try:
        port = int(environ.get("EMAIL_PORT", "587"))
    except ValueError as exc:
        raise SiteConfigError("EMAIL_PORT must be an integer.") from exc
    return {
        "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "EMAIL_HOST": host,
        "EMAIL_PORT": port,
        "EMAIL_HOST_USER": user,
        "EMAIL_HOST_PASSWORD": password,
        "EMAIL_USE_TLS": resolve_bool(environ.get("EMAIL_USE_TLS"), True),
        "EMAIL_USE_SSL": resolve_bool(environ.get("EMAIL_USE_SSL"), False),
        "EMAIL_TIMEOUT": int(environ.get("EMAIL_TIMEOUT", "15")),
        "DEFAULT_FROM_EMAIL": environ.get("DEFAULT_FROM_EMAIL", f"SmartWagers <{user}>"),
        "SERVER_EMAIL": environ.get("SERVER_EMAIL", environ.get("DEFAULT_FROM_EMAIL", f"SmartWagers <{user}>")),
    }


def redis_endpoint(environ: dict[str, str]) -> tuple[str, int]:
    host = environ.get("REDIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(environ.get("REDIS_PORT", "6379"))
    except ValueError as exc:
        raise SiteConfigError("REDIS_PORT must be an integer.") from exc
    return host, port


def location_name(environ: dict[str, str]) -> str:
    raw = environ.get("LOCATION", environ.get("Location", "")).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1].strip()
    return raw


def evaluate_site_config(environ: dict[str, str], *, debug: bool) -> tuple[list[str], list[str]]:
    """Return error and warning messages. Messages name settings and never include secret values."""
    errors: list[str] = []
    warnings: list[str] = []

    def missing(name: str) -> bool:
        return not str(environ.get(name, "")).strip()

    if debug:
        warnings.append("DJANGO_DEBUG is enabled; this configuration must not be used for a remote site.")
        return errors, warnings

    secret = str(environ.get("DJANGO_SECRET_KEY", ""))
    if not secret.strip() or secret.startswith(INSECURE_SECRET_PREFIX):
        errors.append("DJANGO_SECRET_KEY must be set to a unique production value.")
    if missing("DJANGO_ALLOWED_HOSTS"):
        errors.append("DJANGO_ALLOWED_HOSTS is required in production.")
    if missing("DJANGO_CSRF_TRUSTED_ORIGINS"):
        errors.append("DJANGO_CSRF_TRUSTED_ORIGINS is required in production.")
    for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        if missing(name):
            errors.append(f"{name} is required in production.")
    if missing("MASTER_LOCK_SIGNING_KEY"):
        errors.append("MASTER_LOCK_SIGNING_KEY is required in production.")
    if missing("MASTER_LOCK_PASSWORD_HASH"):
        warnings.append("MASTER_LOCK_PASSWORD_HASH is empty. Generate it before tellers use the site.")
    if missing("EMAIL_HOST"):
        warnings.append("EMAIL_HOST is empty; the built-in SMTP default will be used.")
    if missing("EMAIL_HOST_USER"):
        warnings.append("EMAIL_HOST_USER is empty; the built-in sender default will be used.")
    if missing("EMAIL_HOST_PASSWORD") and environ.get("EMAIL_PASSWORD_FILE_PRESENT") != "1":
        warnings.append("EMAIL_HOST_PASSWORD is empty. Commission email needs it or a .email_password file.")
    if missing("LOCATION"):
        warnings.append("LOCATION is empty. Commission email will not name this venue.")
    if missing("REDIS_HOST"):
        warnings.append("REDIS_HOST is empty; Redis defaults to localhost.")
    return errors, warnings
