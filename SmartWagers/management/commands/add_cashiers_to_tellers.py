# myapp/management/commands/add_cashiers_to_tellers.py

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group

class Command(BaseCommand):
    help = "Add cashier-* users to the tellers group"

    def handle(self, *args, **options):
        # Ensure the 'tellers' group exists
        group, created = Group.objects.get_or_create(name="teller")
        if created:
            self.stdout.write(self.style.SUCCESS("Created 'tellers' group"))

        # Find all users whose username starts with 'cashier'
        cashiers = User.objects.filter(username__startswith="cashier")
        if not cashiers.exists():
            self.stdout.write(self.style.WARNING("No cashier users found"))
            return

        for user in cashiers:
            user.groups.add(group)
            self.stdout.write(self.style.SUCCESS(f"Added {user.username} to tellers group"))

        self.stdout.write(self.style.SUCCESS("Finished assigning cashiers to tellers group"))
