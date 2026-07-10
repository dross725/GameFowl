from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Totals


@receiver(post_save, sender=Totals)
def update_total_bet_amount(sender, instance, created, **kwargs):
    pass