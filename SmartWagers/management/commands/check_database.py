from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verify that the configured database accepts a query."

    def handle(self, *args, **options):
        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
        except Exception as exc:
            raise CommandError(f"Database readiness check failed: {exc}") from exc

        if result != (1,):
            raise CommandError(f"Database readiness check returned {result!r}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Database ready: vendor={connection.vendor} "
                f"name={connection.settings_dict.get('NAME')}"
            )
        )
