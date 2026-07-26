from django.db import migrations


def exclude_legacy_transactions(apps, schema_editor):
    """Keep transactions created before the shared fund migration out of it."""
    TellerTransaction = apps.get_model('SmartWagers', 'TellerTransaction')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT applied
            FROM django_migrations
            WHERE app = %s AND name = %s
            """,
            ['SmartWagers', '0029_event_admin_opening_fund_adminbanktransaction'],
        )
        row = cursor.fetchone()

    if row:
        TellerTransaction.objects.filter(
            created_at__lte=row[0],
        ).update(affects_admin_fund=False)


class Migration(migrations.Migration):

    dependencies = [
        (
            'SmartWagers',
            '0029_event_admin_opening_fund_adminbanktransaction',
        ),
    ]

    operations = [
        migrations.RunPython(
            exclude_legacy_transactions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
