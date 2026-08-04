from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .models import Settings, Totals


@receiver(post_save, sender=Totals)
def update_total_bet_amount(sender, instance, created, **kwargs):
    pass


@receiver([post_save, post_delete], sender=Settings)
def clear_commission_cache(sender, **kwargs):
    # Import lazily to avoid a models/services import cycle at app startup.
    from .services import invalidate_comm_cache

    invalidate_comm_cache()