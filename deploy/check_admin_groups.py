"""Quick integrity check for Django admin Groups page failures."""
import django
django.setup()

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

print("groups =", Group.objects.count())
print("permissions =", Permission.objects.count())

bad = []
for p in Permission.objects.select_related("content_type"):
    try:
        str(p)
    except Exception as exc:  # noqa: BLE001
        bad.append((p.pk, p.codename, repr(exc)))
print("bad_permissions =", bad)

orphans = [
    (ct.app_label, ct.model)
    for ct in ContentType.objects.all()
    if ct.model_class() is None
]
print("orphan_content_types =", orphans)
