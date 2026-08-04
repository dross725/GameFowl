from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.apps import apps
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Count, Sum

from SmartWagers import services
from SmartWagers.models import (
    Event,
    Fight_Results,
    Fight_Status,
    TellerTransaction,
    Totals,
    Wagers,
)


def stable_hash(queryset, field_names):
    digest = hashlib.sha256()
    for row in queryset.order_by("pk").values_list(*field_names).iterator(chunk_size=2000):
        encoded = json.dumps(
            row,
            cls=DjangoJSONEncoder,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def model_snapshot(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    queryset = model._default_manager.all()
    return {
        "count": queryset.count(),
        "sha256": stable_hash(queryset, fields),
        "fields": fields,
    }


def through_snapshot(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    return {
        "count": model._default_manager.count(),
        "sha256": stable_hash(model._default_manager.all(), fields),
        "fields": fields,
    }


def duplicate_count(queryset, field_name):
    return (
        queryset.values(field_name)
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .count()
    )


def build_manifest():
    app_models = sorted(
        apps.get_app_config("SmartWagers").get_models(),
        key=lambda model: model._meta.label_lower,
    )
    tracked_models = [User, Group, *app_models]
    models = {
        model._meta.label: model_snapshot(model)
        for model in tracked_models
    }

    memberships = {
        "auth.User_groups": through_snapshot(User.groups.through),
        "auth.User_user_permissions": through_snapshot(User.user_permissions.through),
        "auth.Group_permissions": through_snapshot(Group.permissions.through),
    }

    active_event = services.get_active_event()
    latest_totals = Totals.objects.order_by("-id").first()
    totals_reconciliation = None
    if latest_totals is not None:
        wager_qs = Wagers.objects.filter(
            fightnum=latest_totals.fightnum,
            registered=True,
            cancelled=False,
            side__in=("MERON", "WALA"),
        )
        if active_event is not None:
            wager_qs = wager_qs.filter(created_at__gte=active_event.started_at)
        wager_sums = wager_qs.aggregate(
            meron=Sum("wager", filter=models_module_q(side="MERON")),
            wala=Sum("wager", filter=models_module_q(side="WALA")),
        )
        meron = float(wager_sums["meron"] or 0)
        wala = float(wager_sums["wala"] or 0)
        totals_reconciliation = {
            "fightnum": latest_totals.fightnum,
            "wager_meron": round(meron, 2),
            "stored_meron": round(float(latest_totals.mtotal), 2),
            "wager_wala": round(wala, 2),
            "stored_wala": round(float(latest_totals.wtotal), 2),
            "matches": (
                abs(meron - float(latest_totals.mtotal)) < 0.01
                and abs(wala - float(latest_totals.wtotal)) < 0.01
            ),
        }

    canonical_status = Fight_Status.objects.order_by("id").first()
    duplicate_results = (
        Fight_Results.objects.values("event_id", "fightnum")
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .count()
    )
    payout_summary = TellerTransaction.objects.filter(
        transaction_type=TellerTransaction.PAYOUT
    ).aggregate(count=Count("pk"), amount=Sum("amount"))

    teller_balances = {}
    for user in User.objects.filter(groups__name="teller").distinct().order_by("username"):
        teller_balances[user.username] = round(
            float(services._get_teller_outstanding_balance(user, event=active_event)),
            2,
        )

    invariants = {
        "duplicate_wager_transaction_ids": duplicate_count(Wagers.objects.all(), "transactionid"),
        "duplicate_teller_transaction_ids": duplicate_count(
            TellerTransaction.objects.all(), "transaction_id"
        ),
        "active_event_count": Event.objects.filter(is_active=True).count(),
        "fight_status_row_count": Fight_Status.objects.count(),
        "duplicate_event_fight_results": duplicate_results,
        "totals_reconciliation": totals_reconciliation,
        "cashed_out_wager_count": Wagers.objects.filter(cashed_out=True).count(),
        "payout_ledger_count": payout_summary["count"],
        "payout_ledger_amount": round(float(payout_summary["amount"] or 0), 2),
        "canonical_fight_status": (
            {
                "fightnum": canonical_status.fightnum,
                "overall": canonical_status.overall_status,
                "meron": canonical_status.meron_status,
                "wala": canonical_status.wala_status,
            }
            if canonical_status
            else None
        ),
        "teller_balances": teller_balances,
    }

    return {
        "format_version": 1,
        "database": {
            "vendor": connection.vendor,
            "name": str(connection.settings_dict.get("NAME")),
        },
        "models": models,
        "many_to_many": memberships,
        "invariants": invariants,
    }


def models_module_q(**kwargs):
    # Local helper keeps the import list small while allowing aggregate filters.
    from django.db.models import Q

    return Q(**kwargs)


def strict_problems(manifest):
    invariants = manifest["invariants"]
    problems = []
    if invariants["duplicate_wager_transaction_ids"]:
        problems.append("duplicate wager transaction IDs")
    if invariants["duplicate_teller_transaction_ids"]:
        problems.append("duplicate teller transaction IDs")
    if invariants["active_event_count"] > 1:
        problems.append("multiple active events")
    if invariants["fight_status_row_count"] > 1:
        problems.append("multiple Fight_Status rows")
    if invariants["duplicate_event_fight_results"]:
        problems.append("duplicate event/fight result rows")
    totals = invariants["totals_reconciliation"]
    if totals is not None and not totals["matches"]:
        problems.append("latest totals do not reconcile to registered wagers")
    return problems


class Command(BaseCommand):
    help = "Create or compare a read-only financial/database integrity manifest."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path)
        parser.add_argument("--compare", type=Path)
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        manifest = build_manifest()
        compare_path = options["compare"]
        if compare_path:
            expected = json.loads(compare_path.read_text(encoding="utf-8"))
            mismatches = []
            for section in ("models", "many_to_many"):
                if manifest[section] != expected.get(section):
                    mismatches.append(section)
            if mismatches:
                raise CommandError(
                    "Database differs from source manifest in: " + ", ".join(mismatches)
                )
            self.stdout.write(self.style.SUCCESS("Source and target row data match."))

        if options["strict"]:
            problems = strict_problems(manifest)
            if problems:
                raise CommandError("Integrity checks failed: " + "; ".join(problems))

        output_path = options["output"]
        rendered = json.dumps(manifest, indent=2, cls=DjangoJSONEncoder)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Manifest written: {output_path}"))
        else:
            self.stdout.write(rendered)
