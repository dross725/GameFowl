from django.db import models, transaction as db_transaction
from datetime import datetime
from django.utils.timezone import now
from django.contrib.auth.models import User
import uuid


# Create your models here.
class TransactionSequence(models.Model):
    WAGER = 'WAGER'
    TELLER = 'TELLER'
    key = models.CharField(max_length=20, primary_key=True)
    value = models.BigIntegerField(default=0)

    @classmethod
    def _resync_teller_sequence(cls, sequence):
        """Reset an inflated TELLER counter using current 6-digit transaction IDs.

        Legacy rows may use year-prefixed IDs (e.g. R2026000047) from an older
        format. Those must not block new R000001-style IDs.
        """
        teller_max = 0
        for transaction_id in TellerTransaction.objects.values_list(
            'transaction_id', flat=True,
        ).iterator():
            if not transaction_id or not transaction_id.startswith('R'):
                continue
            suffix = transaction_id[1:]
            if not suffix.isdigit():
                continue
            number = int(suffix)
            if number <= 999999:
                teller_max = max(teller_max, number)
        if teller_max < sequence.value:
            sequence.value = teller_max
            sequence.save(update_fields=['value'])

    @classmethod
    def next_value(cls, key):
        with db_transaction.atomic():
            sequence, _ = cls.objects.select_for_update().get_or_create(
                key=key,
                defaults={'value': 0},
            )
            if key == cls.TELLER and sequence.value >= 999999:
                cls._resync_teller_sequence(sequence)
            if sequence.value >= 999999:
                raise ValueError(f"{key} transaction ID sequence is exhausted.")
            sequence.value += 1
            sequence.save(update_fields=['value'])
            return sequence.value

    def __str__(self):
        return f"{self.key}: {self.value}"


class Wagers (models.Model):
    transactionid = models.CharField(max_length=10, unique=True, editable=False, default='000000')
    fightnum = models.IntegerField(default=0)
    side = models.CharField(max_length=20)
    wager = models.FloatField()
    cashier  = models.CharField(max_length=100, editable=True, default="Juan DelaCruz")
    created_at = models.DateTimeField(default=now)
    cashed_out = models.BooleanField(default=False)
    registered = models.BooleanField(default=True)
    cancelled = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.pk is None and self.cashier == 'System':
            # System wagers get a unique prefixed ID so they never collide with
            # the sequential teller IDs (000001–999999).
            self.transactionid = 'S' + uuid.uuid4().hex[:9].upper()
            super().save(*args, **kwargs)
            return
        if self.pk is None and self.cashier != 'System':
            number = TransactionSequence.next_value(TransactionSequence.WAGER)
            self.transactionid = str(number).zfill(6)
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
    admin_initial_fund = models.FloatField(default=100000.0, null=False, blank=False)
    teller_max_balance = models.FloatField(default=0.0, null=False, blank=False)
    teller_initial_fund = models.FloatField(default=10000.0, null=False, blank=False)
    teller_min_balance = models.FloatField(default=0.0, null=False, blank=False)

    def __str__(self):
        return f"{self.plasada} {self.M_control_status} {self.W_control_status}"

class Fight_Results(models.Model):
    fightnum = models.IntegerField(default=0, blank=False, null=False)
    side = models.CharField(max_length=20)
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
        (COLLECT, 'Borrow'),
        (PAYOUT, 'Payout'),
    ]

    transaction_id = models.CharField(max_length=12, unique=True, editable=False, default='R000000')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teller_transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.FloatField()
    received = models.BooleanField(null=True, blank=True, default=None)
    affects_admin_fund = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'transaction_type']),
        ]

    def save(self, *args, **kwargs):
        if self.pk is None:
            number = TransactionSequence.next_value(TransactionSequence.TELLER)
            self.transaction_id = f"R{str(number).zfill(6)}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_id} | {self.user} | {self.transaction_type} | {self.amount} | {self.created_at}"


class TellerStatus(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teller_status')
    is_online = models.BooleanField(default=True)

    def __str__(self):
        status = 'Online' if self.is_online else 'Offline'
        return f"{self.user} — {status}"


class TellerCloseOut(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='close_outs')
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='teller_close_outs')
    closed_at = models.DateTimeField(default=now)
    fightnum = models.IntegerField()
    expected_cash_on_hand = models.FloatField()
    grand_total = models.FloatField(default=0)
    remit_total = models.FloatField(default=0)
    collect_total = models.FloatField(default=0)
    payout_total = models.FloatField(default=0)
    actual_cash_counted = models.FloatField(null=True, blank=True)
    variance = models.FloatField(null=True, blank=True)
    counted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='counted_close_outs',
    )
    counted_at = models.DateTimeField(null=True, blank=True)
    remit_transaction = models.OneToOneField(
        TellerTransaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='close_out',
    )

    class Meta:
        ordering = ['-closed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'event'],
                name='one_close_out_per_teller_per_event',
            ),
        ]

    def __str__(self):
        return (
            f"{self.user} | {self.event} | fight {self.fightnum} | "
            f"expected={self.expected_cash_on_hand}"
        )


class Event(models.Model):
    name = models.CharField(max_length=200)
    started_at = models.DateTimeField(default=now)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    admin_opening_fund = models.FloatField(default=100000.0)

    class Meta:
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='one_active_event',
            ),
        ]

    def __str__(self):
        status = 'Active' if self.is_active else 'Ended'
        return f"{self.name} ({status}) — {self.started_at.strftime('%Y-%m-%d')}"


class AdminBankTransaction(models.Model):
    BORROW = 'BORROW'
    REMIT = 'REMIT'
    TRANSACTION_TYPES = [
        (BORROW, 'Borrow'),
        (REMIT, 'Remit'),
    ]

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='admin_bank_transactions',
    )
    admin = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='admin_bank_transactions',
    )
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', 'transaction_type']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='admin_bank_transaction_amount_positive',
            ),
        ]

    def __str__(self):
        return (
            f"{self.event} | {self.admin} | "
            f"{self.transaction_type} | {self.amount}"
        )