"""Bootstrap the master lock state file (disabled by default)."""

from django.core.management.base import BaseCommand, CommandError

from SmartWagers import masterlock


class Command(BaseCommand):
    help = (
        'Create the initial disabled master lock state file. '
        'Refuses to overwrite an existing state file.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Overwrite existing state (dangerous recovery only).',
        )

    def handle(self, *args, **options):
        path = masterlock.state_path()
        try:
            payload = masterlock.initialize_state(force=options['force'])
        except masterlock.MasterLockError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Master lock state ready at {path} "
            f"(enabled={payload.get('enabled')}, action={payload.get('action')})"
        ))
