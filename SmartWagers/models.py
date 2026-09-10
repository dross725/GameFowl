from django.db import models, transaction as db_transaction
from datetime import datetime
from django.utils.timezone import now
from django.contrib.auth.models import User
import uuid


# Create your models here.
class TransactionSequence(models.Model):
    WAGER = 'WAGER'
    TELLER = 'TELLER'
    ADMIN_BANK = 'ADMIN_BANK'
    key = models.CharField(max_length=20, primary_key=True)
    value = models.BigIntegerField(default=0)
    cycle = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"{self.key}: {self.value} (cycle {self.cycle})"


class Wagers (models.Model):
    transactionid = models.CharField(max_length=10, unique=True, editable=False, default='000000')
    sequence_cycle = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    fightnum = models.IntegerField(default=0)
    side = models.CharField(max_length=20)
    wager = models.FloatField()
    cashier  = models.CharField(max_length=100, editable=True, default="Juan DelaCruz")
    created_at = models.DateTimeField(default=now)
    cashed_out = models.BooleanField(default=False)
    registered = models.BooleanField(default=True)
    cancelled = models.BooleanField(default=False)
    client_request_id = models.CharField(
        max_length=36,
        null=True,
        blank=True,
        unique=True,
        editable=False,
        help_text="Client-generated UUID for idempotent bet submission.",
    )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            return super().save(*args, **kwargs)
        if self.cashier == 'System':
            # System wagers get a unique prefixed ID so they never collide with
            # the sequential teller IDs (000001–999999).
            self.transactionid = 'S' + uuid.uuid4().hex[:9].upper()
            self.sequence_cycle = None
            return super().save(*args, **kwargs)
        from SmartWagers import transaction_ids

        with db_transaction.atomic():
            transaction_ids.assign_wager_identity(self)
            return super().save(*args, **kwargs)

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
    plasada = models.FloatField(default=0.05, null=False, blank=False)
    M_control_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False) 
    W_control_status = models.CharField(max_length=10, default="OPEN", null=False, blank=False)
    admin_initial_fund = models.FloatField(default=100000.0, null=False, blank=False)
    teller_max_balance = models.FloatField(default=0.0, null=False, blank=False)
    teller_initial_fund = models.FloatField(default=10000.0, null=False, blank=False)
    teller_min_balance = models.FloatField(default=0.0, null=False, blank=False)
    # Reject amounts ending in 3 or 6 (common accidental numpad punch before Enter).
    discard_trailing_3_6 = models.BooleanField(default=True)

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
        (REMIT, 'Advance'),
        (COLLECT, 'Borrow'),
        (PAYOUT, 'Payout'),
    ]

    transaction_id = models.CharField(max_length=12, unique=True, editable=False, default='R000000')
    sequence_cycle = models.PositiveBigIntegerField(default=0, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teller_transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.FloatField()
    received = models.BooleanField(null=True, blank=True, default=None)
    affects_admin_fund = models.BooleanField(default=True)
    cancelled = models.BooleanField(default=False)
    edited = models.BooleanField(default=False)
    updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'transaction_type']),
            models.Index(fields=['cancelled', 'transaction_type']),
        ]

    @property
    def status_key(self):
        """UI status for advance/borrow history rows."""
        if self.cancelled:
            return 'cancelled'
        if self.transaction_type == self.REMIT and self.received:
            return 'received'
        if self.edited:
            return 'edited'
        if self.transaction_type == self.REMIT:
            return 'pending'
        return None

    def is_pending_editable(self):
        """Pending advances (not received, not cancelled) may be edited/cancelled."""
        return (
            self.transaction_type == self.REMIT
            and not self.cancelled
            and not self.received
        )

    def is_editable_by_admin(self):
        """Alias kept for call sites; same rules as is_pending_editable."""
        return self.is_pending_editable()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            return super().save(*args, **kwargs)
        from SmartWagers import transaction_ids

        with db_transaction.atomic():
            transaction_ids.assign_teller_identity(self)
            return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.transaction_id} | {self.user} | "
            f"{self.get_transaction_type_display()} | {self.amount} | {self.created_at}"
        )


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


class TellerWrongPunch(models.Model):
    """Per-teller wrong-punch tally for an event (accidental trailing 3/6)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wrong_punches')
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='wrong_punches')
    count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['count', 'user__username']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'event'],
                name='one_wrong_punch_per_teller_per_event',
            ),
        ]

    def __str__(self):
        return f"{self.user} | {self.event} | wrong punches={self.count}"


class Event(models.Model):
    name = models.CharField(max_length=200)
    started_at = models.DateTimeField(default=now)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    admin_opening_fund = models.FloatField(default=100000.0)
    expected_admin_cash_on_hand = models.FloatField(null=True, blank=True)
    actual_admin_cash_counted = models.FloatField(null=True, blank=True)
    admin_cash_variance = models.FloatField(null=True, blank=True)
    admin_cash_counted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='admin_cash_counts',
    )
    admin_cash_counted_at = models.DateTimeField(null=True, blank=True)

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
        (REMIT, 'Advance'),
    ]

    transaction_id = models.CharField(max_length=12, unique=True, editable=False)
    sequence_cycle = models.PositiveBigIntegerField(default=0, editable=False)
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

    def save(self, *args, **kwargs):
        if self.pk is not None:
            return super().save(*args, **kwargs)
        from SmartWagers import transaction_ids

        with db_transaction.atomic():
            transaction_ids.assign_admin_bank_identity(self)
            return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.transaction_id} | {self.event} | {self.admin} | "
            f"{self.get_transaction_type_display()} | {self.amount}"
        )


class ArchivedWager(models.Model):
    source_pk = models.BigIntegerField(unique=True, editable=False)
    sequence_cycle = models.PositiveBigIntegerField(editable=False)
    transactionid = models.CharField(max_length=10, editable=False)
    fightnum = models.IntegerField()
    side = models.CharField(max_length=20)
    wager = models.FloatField()
    cashier = models.CharField(max_length=100)
    created_at = models.DateTimeField()
    cashed_out = models.BooleanField(default=False)
    registered = models.BooleanField(default=True)
    cancelled = models.BooleanField(default=False)
    client_request_id = models.CharField(max_length=36, null=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='archived_wagers')
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-archived_at']
        constraints = [
            models.UniqueConstraint(
                fields=['sequence_cycle', 'transactionid'],
                name='archived_wager_cycle_transactionid_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['event', 'cashier']),
            models.Index(fields=['event', 'fightnum']),
        ]

    def __str__(self):
        return f"archived {self.transactionid} fight={self.fightnum}"


class ArchivedTellerTransaction(models.Model):
    source_pk = models.BigIntegerField(unique=True, editable=False)
    sequence_cycle = models.PositiveBigIntegerField(editable=False)
    transaction_id = models.CharField(max_length=12, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='archived_teller_transactions')
    transaction_type = models.CharField(max_length=10, choices=TellerTransaction.TRANSACTION_TYPES)
    amount = models.FloatField()
    received = models.BooleanField(null=True, blank=True, default=None)
    affects_admin_fund = models.BooleanField(default=True)
    cancelled = models.BooleanField(default=False)
    edited = models.BooleanField(default=False)
    updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='archived_teller_transactions')
    close_out = models.OneToOneField(
        TellerCloseOut,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='archived_remit_transaction',
    )
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-archived_at']
        constraints = [
            models.UniqueConstraint(
                fields=['sequence_cycle', 'transaction_id'],
                name='archived_teller_cycle_transaction_id_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['event', 'user']),
            models.Index(fields=['event', 'transaction_type']),
        ]

    def __str__(self):
        return f"archived {self.transaction_id} {self.user}"


class ArchivedAdminBankTransaction(models.Model):
    source_pk = models.BigIntegerField(unique=True, editable=False)
    sequence_cycle = models.PositiveBigIntegerField(editable=False)
    transaction_id = models.CharField(max_length=12, editable=False)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='archived_admin_bank_transactions')
    admin = models.ForeignKey(User, on_delete=models.PROTECT, related_name='archived_admin_bank_transactions')
    transaction_type = models.CharField(max_length=10, choices=AdminBankTransaction.TRANSACTION_TYPES)
    amount = models.FloatField()
    created_at = models.DateTimeField()
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-archived_at']
        constraints = [
            models.UniqueConstraint(
                fields=['sequence_cycle', 'transaction_id'],
                name='archived_admin_bank_cycle_transaction_id_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['event', 'admin']),
            models.Index(fields=['event', 'transaction_type']),
        ]

    def __str__(self):
        return f"archived {self.transaction_id} {self.event}"