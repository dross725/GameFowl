from django.db import models
from datetime import datetime
from django.utils.timezone import now
from django.contrib.auth.models import User


# Create your models here.
class Wagers (models.Model):
    transactionid = models.CharField(max_length=10, unique=True, editable=False, default='000000')  # Default value and auto-increment
    fightnum = models.IntegerField(default=0)
    side = models.CharField(max_length=10)
    wager = models.FloatField()
    cashier  = models.CharField(max_length=100, editable=True, default="Juan DelaCruz")
    created_at = models.DateTimeField(default=now)
    cashed_out = models.BooleanField(default=False)
    registered = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        #if not self.transactionid:  # Only generate the code on creation
        if self.pk is None:
            current_year = datetime.now().year
            last_entry = Wagers.objects.order_by('-id').first()  # Get the latest entry
            if last_entry and last_entry.transactionid[:4] == str(current_year):
                # Increment based on the last entry
                last_number = int(last_entry.transactionid[4:]) + 1
            else:
                last_number = 1  # Start fresh for the year
            
            self.transactionid = f"{current_year}{str(last_number).zfill(6)}"
        super().save(*args, **kwargs)  # Call the parent save method

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