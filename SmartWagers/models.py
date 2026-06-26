from django.db import models
from datetime import datetime
from django.utils.timezone import now
from django.contrib.auth.models import User


# Create your models here.
class Wagers (models.Model):
    transactionid = models.CharField(max_length=10, unique=False, editable=False, default='000000')
    fightnum = models.IntegerField(default=0)
    side = models.CharField(max_length=10)
    wager = models.FloatField()
    cashier  = models.CharField(max_length=100, editable=True, default="Juan DelaCruz")
    created_at = models.DateTimeField(default=now)
    cashed_out = models.BooleanField(default=False)
    registered = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.pk is None and self.cashier != 'System':
            from django.apps import apps
            Event = apps.get_model('SmartWagers', 'Event')
            active_event = Event.objects.filter(is_active=True).order_by('-started_at').first()
            qs = Wagers.objects.exclude(cashier='System')
            if active_event:
                qs = qs.filter(created_at__gte=active_event.started_at)
            last_number = 0
            for tid in qs.order_by('-id').values_list('transactionid', flat=True):
                try:
                    n = int(tid)
                    if 0 < n < 1_000_000:
                        last_number = n
                        break
                except (ValueError, TypeError):
                    continue
            self.transactionid = str(last_number + 1).zfill(6)
        super().save(*args, **kwargs)

    def formatted_time(self):
        return (self.created_at).strftime("%Y-%m-%d %H:%M:%S")

    def __str__(self):
        return f"{self.transactionid} {self.fightnum} {self.side} {self.wager} {self.cashier} {self.created_at} {self.cashed_out}"
    

class Totals (models.Model):
    #transaction_id = models.CharField(max_length=10, unique=True, editable=False, default=0000000)  # Default value and auto-increment
    fightnum = models.IntegerField(default=0, blank=False, null=False)
    mtotal = models.FloatField(default=0, blank=False, null=False)
    wtotal = models.FloatField(default=0, blank=False, null=False)
    mpayout = models.FloatField(default=0, blank=False, null=False)
    wpayout = models.FloatField(default=0, blank=False, null=False)
    totalpot = models.FloatField(default=0, blank=False, null=False)

    def __str__(self):
        return f"{self.fightnum} {self.mtotal} {self.mpayout} {self.wtotal} {self.wpayout} {self.totalpot}"


class Settings (models.Model):
    plasada = models.FloatField(default=0.5, null=False, blank=False)
    M_control_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False) 
    W_control_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False)

    def __str__(self):
        return f"{self.plasada} {self.M_control_status} {self.W_control_status}"

class Fight_Results(models.Model):
    fightnum = models.IntegerField(default=0, blank=False, null=False)
    side = models.CharField(max_length=5)
    mtotal = models.FloatField(default=0, blank=False, null=False)
    wtotal = models.FloatField(default=0, blank=False, null=False)
    mpayout = models.FloatField(default=0, blank=False, null=False)
    wpayout = models.FloatField(default=0, blank=False, null=False) 
    totalpot = models.FloatField(default=0, blank=False, null=False)
    odds = models.CharField(max_length=10)
    date = models.DateField(default=datetime.today)
    event = models.ForeignKey('Event', null=True, blank=True, on_delete=models.SET_NULL, related_name='fight_results')

    def __str__(self):
        return f"{self.fightnum} {self.side} {self.odds} {self.mtotal} {self.mpayout} {self.wtotal} {self.wpayout} {self.totalpot} {self.date}"

class Fight_Status(models.Model):
    fightnum = models.IntegerField(default=0, blank=False, null=False)
    overall_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False)  # OPEN, CLOSEd, etc.
    meron_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False)  # OPEN, Closed, etc.
    wala_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False)  # OPEN, Closed, etc.
    date = models.DateField(default=datetime.today)

    def __str__(self):
        return f"{self.fightnum} {self.overall_status} {self.meron_status} {self.wala_status}"
    


class SessionLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-login_time']
        indexes = [
            models.Index(fields=['user', 'login_time']),
        ]

    def duration(self):
        if self.logout_time:
            return self.logout_time - self.login_time
        return None
    
    def __str__(self):
        return f"{self.user} | {self.login_time} → {self.logout_time or 'Active'}"


class TellerTransaction(models.Model):
    REMIT = 'REMIT'
    COLLECT = 'COLLECT'
    PAYOUT = 'PAYOUT'
    TRANSACTION_TYPES = [
        (REMIT, 'Remit'),
        (COLLECT, 'Collect'),
        (PAYOUT, 'Payout'),
    ]

    transaction_id = models.CharField(max_length=12, unique=False, editable=False, default='R000000')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teller_transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.FloatField()
    received = models.BooleanField(null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'transaction_type']),
        ]

    def save(self, *args, **kwargs):
        if self.pk is None:
            from django.apps import apps
            Event = apps.get_model('SmartWagers', 'Event')
            active_event = Event.objects.filter(is_active=True).order_by('-started_at').first()
            qs = TellerTransaction.objects.all()
            if active_event:
                qs = qs.filter(created_at__gte=active_event.started_at)
            last_number = 0
            for tid in qs.order_by('-id').values_list('transaction_id', flat=True):
                try:
                    n = int(tid[1:])  # strip leading 'R'
                    if 0 < n < 1_000_000:
                        last_number = n
                        break
                except (ValueError, TypeError, IndexError):
                    continue
            self.transaction_id = f"R{str(last_number + 1).zfill(6)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_id} | {self.user} | {self.transaction_type} | {self.amount} | {self.created_at}"


class Event(models.Model):
    name = models.CharField(max_length=200)
    started_at = models.DateTimeField(default=now)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        status = 'Active' if self.is_active else 'Ended'
        return f"{self.name} ({status}) — {self.started_at.strftime('%Y-%m-%d')}"