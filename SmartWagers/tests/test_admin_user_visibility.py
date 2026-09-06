import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client, override_settings


def _grant_user_admin_perms(user):
    for codename in ('view_user', 'change_user', 'add_user', 'delete_user'):
        perm = Permission.objects.get(
            codename=codename, content_type__app_label='auth',
        )
        user.user_permissions.add(perm)


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=['*'])
def test_staff_admin_hides_superusers_from_changelist():
    staff = User.objects.create_user(username='staffonly', password='Ab12Cd34')
    staff.is_staff = True
    staff.save()
    _grant_user_admin_perms(staff)

    User.objects.create_superuser(username='hidden_su', password='Ab12Cd34')
    User.objects.create_user(username='regular', password='Ab12Cd34')

    client = Client()
    assert client.login(username='staffonly', password='Ab12Cd34')
    response = client.get('/admin/auth/user/')
    content = response.content.decode()

    assert response.status_code == 200
    assert 'hidden_su' not in content
    assert 'regular' in content
    assert 'is_superuser__exact' not in content


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=['*'])
def test_staff_cannot_open_superuser_change_page():
    staff = User.objects.create_user(username='staffonly', password='Ab12Cd34')
    staff.is_staff = True
    staff.save()
    _grant_user_admin_perms(staff)

    su = User.objects.create_superuser(username='hidden_su', password='Ab12Cd34')

    client = Client()
    assert client.login(username='staffonly', password='Ab12Cd34')
    response = client.get(f'/admin/auth/user/{su.pk}/change/')
    assert response.status_code == 302  # redirected away / not found


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=['*'])
def test_staff_user_form_hides_superuser_field():
    staff = User.objects.create_user(username='staffonly', password='Ab12Cd34')
    staff.is_staff = True
    staff.save()
    _grant_user_admin_perms(staff)

    regular = User.objects.create_user(username='regular', password='Ab12Cd34')

    client = Client()
    assert client.login(username='staffonly', password='Ab12Cd34')
    response = client.get(f'/admin/auth/user/{regular.pk}/change/')
    content = response.content.decode()

    assert response.status_code == 200
    assert 'id_is_superuser' not in content
    assert 'id_is_staff' in content


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=['*'])
def test_superuser_admin_sees_superusers_and_field():
    su = User.objects.create_superuser(username='root_su', password='Ab12Cd34')
    User.objects.create_superuser(username='other_su', password='Ab12Cd34')

    client = Client()
    assert client.login(username='root_su', password='Ab12Cd34')
    response = client.get('/admin/auth/user/')
    content = response.content.decode()

    assert response.status_code == 200
    assert 'other_su' in content
    assert 'is_superuser__exact' in content
