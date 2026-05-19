from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Totals
from django.db import connection

@receiver(post_save, sender=Totals)
def update_total_bet_amount(sender, instance, created, **kwargs):
    # This can be a place to perform actions when a Bet is created
    # or updated. However, the total_amount will be calculated directly
    # in the views instead of managing it through another mechanism.
    if created:
        with connection.cursor() as cursor:
            cursor.execute("SELECT SUM(amount) FROM bets_bet")