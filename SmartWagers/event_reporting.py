"""Shared event commission report used by the admin page and end-event email."""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.db import transaction as db_transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.timezone import now

from .models import Event, EventReportEmail, Fight_Results

logger = logging.getLogger('SmartWagers.event_reporting')

NON_COMMISSION_SIDES = ('CANCELLED', 'DRAW')


def fight_commission(totalpot, side, plasada):
    """Commission is total pot times plasada, except draws and cancellations."""
    if side in NON_COMMISSION_SIDES:
        return 0.0
    return float(totalpot or 0) * float(plasada or 0)


def _iso(value):
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def build_commission_report(event=None, plasada=None, *, json_safe=False):
    """Return per-fight commission rows and grand totals for one event.

    ``event=None`` includes every stored fight result. ``json_safe=True``
    converts dates so the snapshot can be stored and rendered later.
    """
    if plasada is None:
        from .services import get_comm_val
        plasada = get_comm_val()
    plasada = float(plasada or 0)

    results = Fight_Results.objects.all().order_by('fightnum', 'id')
    if event is not None:
        results = results.filter(event=event)

    fights = []
    total_pot = 0.0
    total_commission = 0.0
    for result in results:
        commission = fight_commission(result.totalpot, result.side, plasada)
        counted = result.side not in NON_COMMISSION_SIDES
        if counted:
            total_pot += float(result.totalpot or 0)
        total_commission += commission
        fights.append({
            'fightnum': result.fightnum,
            'side': result.side,
            'mtotal': result.mtotal,
            'wtotal': result.wtotal,
            'mpayout': result.mpayout,
            'wpayout': result.wpayout,
            'totalpot': result.totalpot,
            'commission': commission,
            'date': _iso(result.date) if json_safe else result.date,
        })

    return {
        'event_id': event.pk if event is not None else None,
        'event_name': event.name if event is not None else '',
        'started_at': _iso(event.started_at) if event is not None else None,
        'ended_at': _iso(event.ended_at) if event is not None else None,
        'location': getattr(settings, 'LOCATION', ''),
        'plasada': plasada,
        'plasada_pct': plasada * 100,
        'fights': fights,
        'total_pot': total_pot,
        'total_commission': total_commission,
        'fight_count': len(fights),
    }


def snapshot_superuser_recipients():
    """Sender plus active superusers, de-duplicated by email address."""
    recipients = []
    missing = []
    seen = set()

    sender = (getattr(settings, 'EMAIL_HOST_USER', '') or '').strip()
    if sender:
        seen.add(sender.lower())
        recipients.append(sender)

    users = User.objects.filter(is_superuser=True, is_active=True).order_by('pk')
    for user in users:
        email = (user.email or '').strip()
        if not email:
            missing.append(user.username)
            logger.warning(
                'EVENT REPORT EMAIL: superuser %s has no email address',
                user.username,
            )
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients, missing


def queue_event_commission_email(event):
    """Create the single outbox row for an event and schedule delivery on commit."""
    existing = EventReportEmail.objects.filter(event=event).first()
    if existing is not None:
        return existing

    recipients, missing = snapshot_superuser_recipients()
    payload = build_commission_report(event, json_safe=True)
    status = (
        EventReportEmail.STATUS_NO_RECIPIENTS
        if not recipients
        else EventReportEmail.STATUS_PENDING
    )
    row = EventReportEmail.objects.create(
        event=event,
        recipients=recipients,
        missing_superusers=missing,
        payload=payload,
        status=status,
    )
    if not recipients:
        logger.warning(
            'EVENT REPORT EMAIL: no recipients for event id=%s name=%r',
            event.pk,
            event.name,
        )
        return row

    email_id = row.pk
    db_transaction.on_commit(
        lambda email_id=email_id: deliver_event_report_email(email_id),
    )
    return row


def event_report_email_warning(event):
    """Operator-facing warning when the closeout email did not go out."""
    row = EventReportEmail.objects.filter(event=event).first()
    if row is None:
        return None
    if row.status == EventReportEmail.STATUS_NO_RECIPIENTS:
        return (
            'Commission report was not emailed because neither EMAIL_HOST_USER '
            'nor an active superuser has an email address.'
        )
    if row.status == EventReportEmail.STATUS_FAILED:
        return (
            'Event ended, but the commission email could not be sent and will '
            'be retried.'
        )
    return None


def _send_commission_email(row):
    if not getattr(settings, 'EMAIL_HOST', ''):
        raise RuntimeError('EMAIL_HOST is not configured.')
    if (
        getattr(settings, 'EMAIL_BACKEND', '').endswith(
            '.smtp.EmailBackend',
        )
        and getattr(settings, 'EMAIL_HOST_USER', '')
        and not getattr(settings, 'EMAIL_HOST_PASSWORD', '')
    ):
        raise RuntimeError(
            'Email password is not configured. Create the local '
            '.email_password file.',
        )
    payload = row.payload or {}
    context = {
        'report': payload,
        'fights': payload.get('fights') or [],
        'recipients': row.recipients,
    }
    event_name = payload.get('event_name') or f'Event {row.event_id}'
    subject = f'SmartWagers commission report — {event_name}'
    text_body = render_to_string(
        'SmartWagers/email/commission_report.txt',
        context,
    )
    html_body = render_to_string(
        'SmartWagers/email/commission_report.html',
        context,
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[],
        bcc=list(row.recipients),
    )
    message.attach_alternative(html_body, 'text/html')
    message.send(fail_silently=False)


def deliver_event_report_email(email_id):
    """Send one outbox row. Sent rows are never sent again."""
    from datetime import timedelta

    with db_transaction.atomic():
        row = (
            EventReportEmail.objects
            .select_for_update()
            .filter(pk=email_id)
            .first()
        )
        if row is None:
            return 'missing'
        if row.status == EventReportEmail.STATUS_SENT:
            return 'skipped'
        if row.status == EventReportEmail.STATUS_SENDING:
            stale_before = now() - timedelta(
                seconds=int(getattr(settings, 'EMAIL_TIMEOUT', 15)) + 30,
            )
            if row.updated_at and row.updated_at >= stale_before:
                return 'skipped'
        if not row.recipients:
            if row.status != EventReportEmail.STATUS_NO_RECIPIENTS:
                row.status = EventReportEmail.STATUS_NO_RECIPIENTS
                row.save(update_fields=['status', 'updated_at'])
            return 'no_recipients'
        row.status = EventReportEmail.STATUS_SENDING
        row.attempts += 1
        row.save(update_fields=['status', 'attempts', 'updated_at'])

    try:
        _send_commission_email(row)
    except Exception as exc:
        logger.exception(
            'EVENT REPORT EMAIL failed id=%s event=%s attempt=%s',
            row.pk,
            row.event_id,
            row.attempts,
        )
        EventReportEmail.objects.filter(pk=row.pk).exclude(
            status=EventReportEmail.STATUS_SENT,
        ).update(
            status=EventReportEmail.STATUS_FAILED,
            last_error=str(exc)[:2000],
            updated_at=now(),
        )
        return 'failed'

    EventReportEmail.objects.filter(pk=row.pk).exclude(
        status=EventReportEmail.STATUS_SENT,
    ).update(
        status=EventReportEmail.STATUS_SENT,
        sent_at=now(),
        last_error='',
        updated_at=now(),
    )
    logger.info(
        'EVENT REPORT EMAIL sent id=%s event=%s recipients=%s',
        row.pk,
        row.event_id,
        len(row.recipients),
    )
    return 'sent'


def list_events_for_report():
    """Return events newest first, with the commission-email status when one exists."""
    emails = {
        row.event_id: row
        for row in EventReportEmail.objects.all()
    }
    listed = []
    for event in Event.objects.order_by('-started_at', '-pk'):
        email = emails.get(event.pk)
        listed.append({
            'id': event.pk,
            'name': event.name,
            'is_active': event.is_active,
            'started_at': event.started_at,
            'ended_at': event.ended_at,
            'email_status': email.status if email is not None else 'not_queued',
        })
    return listed


def resend_event_commission_email(event_id):
    """Send one event again, preserving its original report snapshot when present."""
    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        return {'ok': False, 'error': 'not_found'}

    recipients, missing = snapshot_superuser_recipients()
    existing = EventReportEmail.objects.filter(event=event).first()
    payload = (
        existing.payload
        if existing is not None and existing.payload
        else build_commission_report(event, json_safe=True)
    )
    row, _created = EventReportEmail.objects.get_or_create(
        event=event,
        defaults={
            'recipients': recipients,
            'missing_superusers': missing,
            'payload': payload,
            'status': (
                EventReportEmail.STATUS_NO_RECIPIENTS
                if not recipients
                else EventReportEmail.STATUS_PENDING
            ),
        },
    )
    row.recipients = recipients
    row.missing_superusers = missing
    row.payload = payload
    row.last_error = ''
    if not recipients:
        row.status = EventReportEmail.STATUS_NO_RECIPIENTS
        row.save(update_fields=[
            'recipients', 'missing_superusers', 'payload', 'last_error',
            'status', 'updated_at',
        ])
        logger.warning(
            'EVENT REPORT EMAIL resend: no recipients for event id=%s name=%r',
            event.pk,
            event.name,
        )
        return {'ok': False, 'error': 'no_recipients', 'event_id': event.pk}

    row.status = EventReportEmail.STATUS_PENDING
    row.save(update_fields=[
        'recipients', 'missing_superusers', 'payload', 'last_error',
        'status', 'updated_at',
    ])
    outcome = deliver_event_report_email(row.pk)
    return {
        'ok': outcome == 'sent',
        'outcome': outcome,
        'event_id': event.pk,
        'event_name': event.name,
    }


def send_pending_event_reports():
    """Retry pending and failed commission emails. Sent rows are left alone."""
    from datetime import timedelta

    sent = failed = skipped = 0
    stale_before = now() - timedelta(
        seconds=int(getattr(settings, 'EMAIL_TIMEOUT', 15)) + 30,
    )
    pending_ids = list(
        EventReportEmail.objects.filter(
            Q(status__in=(
                EventReportEmail.STATUS_PENDING,
                EventReportEmail.STATUS_FAILED,
            ))
            | Q(
                status=EventReportEmail.STATUS_SENDING,
                updated_at__lt=stale_before,
            ),
        ).order_by('id').values_list('pk', flat=True)
    )
    for email_id in pending_ids:
        outcome = deliver_event_report_email(email_id)
        if outcome == 'sent':
            sent += 1
        elif outcome == 'failed':
            failed += 1
        else:
            skipped += 1
    return {'sent': sent, 'failed': failed, 'skipped': skipped}
