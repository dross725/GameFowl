import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from GameFowl.site_config import evaluate_site_config


class Command(BaseCommand):
    help = "Validate production site configuration without printing secret values."

    def handle(self, *args, **options):
        environ = dict(os.environ)
        password_file = settings.BASE_DIR / ".email_password"
        if password_file.is_file() and password_file.read_text(encoding="utf-8").strip():
            environ["EMAIL_PASSWORD_FILE_PRESENT"] = "1"
        errors, warnings = evaluate_site_config(environ, debug=settings.DEBUG)
        for warning in warnings:
            self.stdout.write(self.style.WARNING(warning))
        if errors:
            for error in errors:
                self.stderr.write(error)
            raise CommandError("Site configuration is not ready for production.")
        self.stdout.write(self.style.SUCCESS("Site configuration names are valid."))
