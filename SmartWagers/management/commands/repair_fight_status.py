from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from SmartWagers.models import Fight_Status


class Command(BaseCommand):
    help = (
        "Inspect Fight_Status rows and optionally keep only the canonical "
        "lowest-id row used by the application."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete all Fight_Status rows except the lowest-id canonical row.",
        )

    def handle(self, *args, **options):
        rows = list(Fight_Status.objects.order_by("id"))
        if not rows:
            raise CommandError("No Fight_Status rows found.")

        self.stdout.write(f"Fight_Status row count: {len(rows)}")
        for row in rows:
            marker = "KEEP" if row.pk == rows[0].pk else "DELETE"
            self.stdout.write(
                f"  [{marker}] id={row.pk} fightnum={row.fightnum} "
                f"overall={row.overall_status} meron={row.meron_status} "
                f"wala={row.wala_status} date={row.date}"
            )

        if len(rows) == 1:
            self.stdout.write(self.style.SUCCESS("Already healthy: exactly one row."))
            return

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Re-run with --apply to delete the extra rows."
                )
            )
            return

        keep = rows[0]
        with transaction.atomic():
            deleted, _ = Fight_Status.objects.exclude(pk=keep.pk).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Kept id={keep.pk}; deleted {deleted} extra Fight_Status row(s)."
            )
        )
