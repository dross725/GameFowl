"""Retry commission emails that were not sent when an event ended."""

from django.core.management.base import BaseCommand

from SmartWagers.event_reporting import send_pending_event_reports


class Command(BaseCommand):
    help = (
        'Send pending or failed end-of-event commission reports. '
        'Reports that already succeeded are not sent again.'
    )

    def handle(self, *args, **options):
        result = send_pending_event_reports()
        self.stdout.write(
            'sent={sent} failed={failed} skipped={skipped}'.format(**result)
        )
