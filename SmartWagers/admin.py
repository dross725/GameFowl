from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    Wagers, Totals, Settings, Fight_Results, Fight_Status, SessionLog,
    TellerTransaction, AdminBankTransaction, ArchivedWager,
    ArchivedTellerTransaction, ArchivedAdminBankTransaction, TellerStatus,
    TellerWrongPunch,
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
admin.site.register(TellerStatus)
admin.site.register(TellerWrongPunch)


def _strip_superuser_fields(fieldsets):
    """Remove is_superuser from admin fieldsets tuples."""
    cleaned = []
    for name, opts in fieldsets:
        fields = opts.get('fields')
        if not fields:
            cleaned.append((name, opts))
            continue
        new_fields = tuple(f for f in fields if f != 'is_superuser')
        if new_fields != fields:
            opts = {**opts, 'fields': new_fields}
        cleaned.append((name, opts))
    return cleaned


class HiddenSuperuserUserAdmin(BaseUserAdmin):
    """Hide superusers (and superuser controls) from non-superuser staff."""

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
        return qs

    def get_list_filter(self, request):
        filters = list(super().get_list_filter(request))
        if not request.user.is_superuser:
            filters = [f for f in filters if f != 'is_superuser']
        return filters

    def get_list_display(self, request):
        display = list(super().get_list_display(request))
        if not request.user.is_superuser:
            display = [f for f in display if f != 'is_superuser']
        return display

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if not request.user.is_superuser:
            fieldsets = _strip_superuser_fields(fieldsets)
        return fieldsets

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser and 'is_superuser' in form.base_fields:
            form.base_fields.pop('is_superuser')
        return form

    def save_model(self, request, obj, form, change):
        # Non-superusers must never create or promote superusers.
        if not request.user.is_superuser:
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

    def _can_access_user(self, request, obj):
        if obj is None:
            return True
        if obj.is_superuser and not request.user.is_superuser:
            return False
        return True

    def has_view_permission(self, request, obj=None):
        if not self._can_access_user(request, obj):
            return False
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if not self._can_access_user(request, obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if not self._can_access_user(request, obj):
            return False
        return super().has_delete_permission(request, obj)


def register_hidden_superuser_user_admin():
    """(Re)register User admin so superusers stay hidden from staff."""
    try:
        admin.site.unregister(User)
    except admin.sites.NotRegistered:
        pass
    admin.site.register(User, HiddenSuperuserUserAdmin)


register_hidden_superuser_user_admin()
