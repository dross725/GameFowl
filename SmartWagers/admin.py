from django.contrib import admin
from .models import (
    Wagers, Totals, Settings, Fight_Results, Fight_Status, SessionLog,
    TellerTransaction, AdminBankTransaction, ArchivedWager,
    ArchivedTellerTransaction, ArchivedAdminBankTransaction,
)
# Register your models here.
admin.site.register(Wagers)
admin.site.register(Totals)
admin.site.register(Settings)
admin.site.register(Fight_Results)
admin.site.register(Fight_Status)
admin.site.register(SessionLog)
admin.site.register(TellerTransaction)
admin.site.register(AdminBankTransaction)
admin.site.register(ArchivedWager)
admin.site.register(ArchivedTellerTransaction)
admin.site.register(ArchivedAdminBankTransaction)