"""List events and the status of each commission report."""

from django.core.management.base import BaseCommand

from SmartWagers.event_reporting import list_events_for_report


class Command(BaseCommand):
    help = 'List events and whether each commission report has been emailed.'

    def handle(self, *args, **options):
        events = list_events_for_report()
        if not events:
            self.stdout.write('No events.')
            return

        self.stdout.write(
            f'{"ID":<6} {"STATE":<8} {"EMAIL":<14} {"STARTED":<20} {"ENDED":<20} NAME'
        )
        for event in events:
            started = _format_when(event['started_at'])
            ended = _format_when(event['ended_at'])
            state = 'active' if event['is_active'] else 'ended'
            self.stdout.write(
                f'{event["id"]:<6} {state:<8} {event["email_status"]:<14} '
                f'{started:<20} {ended:<20} {event["name"]}'
            )


def _format_when(value):
    if value is None:
        return '—'
    return value.strftime('%Y-%m-%d %H:%M:%S')
