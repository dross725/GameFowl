"""Generate a Django password hash for the master lock key (stdin)."""

import getpass
import sys

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Hash a master lock key for MASTER_LOCK_PASSWORD_HASH. '
        'Reads the key from a prompt (or --key for non-interactive use). '
        'The plaintext key is never written to disk by this command.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--key',
            default='',
            help='Master key (prefer interactive prompt; avoid shell history).',
        )

    def handle(self, *args, **options):
        raw = options.get('key') or ''
        if not raw:
            raw = getpass.getpass('Master lock key: ')
            confirm = getpass.getpass('Confirm master lock key: ')
            if raw != confirm:
                self.stderr.write(self.style.ERROR('Keys do not match.'))
                sys.exit(1)
        if not raw:
            self.stderr.write(self.style.ERROR('Empty key rejected.'))
            sys.exit(1)

        digest = make_password(raw)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Paste this single line into your .env file:'))
        self.stdout.write('')
        self.stdout.write(f'MASTER_LOCK_PASSWORD_HASH={digest}')
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            'Then save .env, run: python manage.py init_master_lock'
        ))
        self.stdout.write(self.style.NOTICE(
            'Store the plaintext master key offline — it is not saved by the app.'
        ))
