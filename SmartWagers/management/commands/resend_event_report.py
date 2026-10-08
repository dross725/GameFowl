"""Resend the commission report for one event."""

from django.core.management.base import BaseCommand, CommandError

from SmartWagers.event_reporting import resend_event_commission_email


class Command(BaseCommand):
    help = (
        'Resend the commission report for one event. '
        'Use list_events to see event IDs. This sends again even if a previous report succeeded.'
    )

    def add_arguments(self, parser):
        parser.add_argument('event_id', type=int, help='Event ID from list_events.')

    def handle(self, *args, **options):
        result = resend_event_commission_email(options['event_id'])
        if result.get('error') == 'not_found':
            raise CommandError(f'No event with ID {options["event_id"]}.')
        if result.get('error') == 'no_recipients':
            raise CommandError(
                f'Event {result["event_id"]} was not emailed because neither '
                'EMAIL_HOST_USER nor an active superuser has an email address.'
            )
        if not result.get('ok'):
            raise CommandError(
                f'Event {result["event_id"]} ({result["event_name"]}) '
                f'was not sent ({result["outcome"]}).'
            )
        self.stdout.write(self.style.SUCCESS(
            f'Sent commission report for event {result["event_id"]} ({result["event_name"]}).'
        ))
