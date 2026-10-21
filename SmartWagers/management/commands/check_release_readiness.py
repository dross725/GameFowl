from django.core.management.base import BaseCommand, CommandError

from SmartWagers.operations_status import readiness_payload


class Command(BaseCommand):
    help = "Check database, Redis, migrations, master lock, and release metadata."

    def handle(self, *args, **options):
        ok, payload = readiness_payload()
        if not ok:
            failed = [name for name, item in payload["checks"].items() if not item.get("ok")]
            raise CommandError("Release readiness failed: " + ", ".join(failed))
        self.stdout.write(self.style.SUCCESS("Release readiness ok."))
