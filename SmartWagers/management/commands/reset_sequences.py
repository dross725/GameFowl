from django.apps import apps
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Reset database sequences after importing records with explicit IDs."

    def handle(self, *args, **options):
        models = [
            User,
            Group,
            *apps.get_app_config("SmartWagers").get_models(),
        ]
        statements = connection.ops.sequence_reset_sql(no_style(), models)
        if not statements:
            self.stdout.write(
                self.style.WARNING(
                    f"No sequence reset statements required for {connection.vendor}."
                )
            )
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

        self.stdout.write(
            self.style.SUCCESS(f"Reset {len(statements)} database sequence(s).")
        )
