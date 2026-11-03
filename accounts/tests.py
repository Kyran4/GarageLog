import re

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from accounts.backends import EmailOrUsernameBackend
from accounts.models import User
from vehicles.models import Vehicle
from workshops.models import Workshop

pytestmark = pytest.mark.django_db

SIGNUP_DATA = {
    'username': 'newcustomer',
    'email': 'new@example.com',
    'first_name': 'New',
    'last_name': 'Customer',
    'phone': '021 123 4567',
    'password1': 'Str0ng-Passw0rd!',
    'password2': 'Str0ng-Passw0rd!',
}


def is_logged_in(client):
    return '_auth_user_id' in client.session


def link_from_email(message, fragment):
    """Return the path of the first link in an email body that contains `fragment`."""
    for match in re.finditer(r'https?://[^\s/]+(/\S*)', message.body):
        if fragment in match.group(1):
            return match.group(1)
    raise AssertionError(f'no {fragment} link in email:\n{message.body}')


# ---------------------------------------------------------------- model


def test_createsuperuser_gets_admin_role_and_approval(db):
    user = User.objects.create_superuser('boss', 'boss@example.com', 'pw-Str0ng-123')
    assert user.role == User.Role.ADMIN
    assert user.is_approved


def test_superuser_is_always_treated_as_admin(make_user):
    user = make_user('root', User.Role.CUSTOMER, is_superuser=True)
    assert user.is_admin_role
    assert not user.is_customer


def test_email_is_stored_lowercase(make_user):
    user = make_user('mixed', email='Mixed.Case@Example.COM')
    assert User.objects.get(pk=user.pk).email == 'mixed.case@example.com'


# ---------------------------------------------------------------- signup


def test_signup_page_loads(client):
    assert client.get(reverse('accounts:signup')).status_code == 200


def test_signup_creates_customer_pending_admin_approval_without_sending_email(client):
    response = client.post(reverse('accounts:signup'), SIGNUP_DATA)

    assert response.status_code == 302
    assert response.url == reverse('accounts:signup_done')
    user = User.objects.get(username='newcustomer')
    assert user.role == User.Role.CUSTOMER
    assert not user.is_active
    assert not user.is_approved
    assert user.check_password('Str0ng-Passw0rd!')
    assert mail.outbox == []


def test_signup_cannot_set_role_or_staff_flags(client):
    data = {**SIGNUP_DATA, 'role': 'ADMIN', 'is_staff': 'on', 'is_superuser': 'on', 'is_active': 'on'}
    client.post(reverse('accounts:signup'), data)

    user = User.objects.get(username='newcustomer')
    assert user.role == User.Role.CUSTOMER
    assert not user.is_staff
    assert not user.is_superuser
    assert not user.is_active


def test_admin_can_approve_and_activate_pending_signup(client):
    client.post(reverse('accounts:signup'), SIGNUP_DATA)
    user = User.objects.get(username='newcustomer')
    admin_user = User.objects.create_superuser(
        'siteadmin', 'admin@example.com', 'Adm1n-Strong-Pass!',
    )
    client.force_login(admin_user)

    response = client.post(
        reverse('admin:accounts_user_changelist'),
        {'action': 'approve_users', '_selected_action': [str(user.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.is_approved
    assert user.is_active
    client.logout()
    response = client.post(reverse('accounts:login'), {
        'username': user.username,
        'password': SIGNUP_DATA['password1'],
    })
    assert response.status_code == 302
    assert is_logged_in(client)


def test_signup_rejects_duplicate_email_ignoring_case(client, customer):
    data = {**SIGNUP_DATA, 'email': 'CUSTOMER@example.com'}
    response = client.post(reverse('accounts:signup'), data)

    assert response.status_code == 200
    assert 'email' in response.context['form'].errors
    assert not User.objects.filter(username='newcustomer').exists()


@pytest.mark.parametrize('overrides, bad_field', [
    ({'password2': 'something-else-123'}, 'password2'),
    ({'password1': 'short', 'password2': 'short'}, 'password2'),
    ({'password1': '12345678', 'password2': '12345678'}, 'password2'),
    ({'email': 'not-an-email'}, 'email'),
    ({'first_name': ''}, 'first_name'),
    ({'phone': 'call me maybe'}, 'phone'),
])
def test_signup_validation_errors(client, overrides, bad_field):
    response = client.post(reverse('accounts:signup'), {**SIGNUP_DATA, **overrides})

    assert response.status_code == 200
    assert bad_field in response.context['form'].errors
    assert not User.objects.filter(username='newcustomer').exists()
    assert mail.outbox == []


def test_signup_phone_is_optional(client):
    response = client.post(reverse('accounts:signup'), {**SIGNUP_DATA, 'phone': ''})
    assert response.status_code == 302


def test_logged_in_user_is_redirected_away_from_signup(client, customer):
    client.force_login(customer)
    response = client.get(reverse('accounts:signup'))
    assert response.status_code == 302
    assert response.url == reverse('dashboard')


# ---------------------------------------------------------------- login / logout


def test_login_page_loads(client):
    assert client.get(reverse('accounts:login')).status_code == 200


def test_approved_user_can_log_in_with_username(client, customer, password):
    response = client.post(reverse('accounts:login'), {'username': 'customer', 'password': password})

    assert response.status_code == 302
    assert response.url == reverse('dashboard')
    assert is_logged_in(client)


def test_user_can_log_in_with_email_in_any_case(client, customer, password):
    response = client.post(reverse('accounts:login'), {'username': 'Customer@EXAMPLE.com', 'password': password})

    assert response.status_code == 302
    assert is_logged_in(client)


def test_login_respects_safe_next_parameter(client, customer, password):
    response = client.post(
        reverse('accounts:login') + '?next=/accounts/profile/',
        {'username': 'customer', 'password': password, 'next': '/accounts/profile/'},
    )
    assert response.url == '/accounts/profile/'


def test_login_ignores_external_next_parameter(client, customer, password):
    response = client.post(
        reverse('accounts:login'),
        {'username': 'customer', 'password': password, 'next': 'https://evil.example.com/'},
    )
    assert response.url == reverse('dashboard')


def test_wrong_password_shows_error_and_does_not_log_in(client, customer):
    response = client.post(reverse('accounts:login'), {'username': 'customer', 'password': 'wrong-password'})

    assert response.status_code == 200
    assert 'username/email or password is incorrect' in response.content.decode()
    assert not is_logged_in(client)


def test_unknown_user_gets_same_error_as_wrong_password(client, db):
    response = client.post(reverse('accounts:login'), {'username': 'ghost', 'password': 'whatever-123'})

    assert response.status_code == 200
    assert 'username/email or password is incorrect' in response.content.decode()


def test_unapproved_user_is_told_to_wait_for_admin_approval(client, make_user, password):
    make_user('pending', is_active=False, is_approved=False)

    response = client.post(reverse('accounts:login'), {'username': 'pending', 'password': password})

    assert response.status_code == 200
    assert 'awaiting admin approval' in response.content.decode()
    assert not is_logged_in(client)


def test_unapproved_account_with_wrong_password_gets_generic_error(client, make_user):
    make_user('pending', is_active=False, is_approved=False)

    response = client.post(reverse('accounts:login'), {'username': 'pending', 'password': 'wrong-password'})

    assert 'username/email or password is incorrect' in response.content.decode()


def test_disabled_user_is_told_account_is_disabled(client, make_user, password):
    make_user('blocked', is_active=False, is_approved=True)

    response = client.post(reverse('accounts:login'), {'username': 'blocked', 'password': password})

    assert 'has been disabled' in response.content.decode()
    assert not is_logged_in(client)


def test_logged_in_user_visiting_login_is_redirected(client, customer):
    client.force_login(customer)
    response = client.get(reverse('accounts:login'))
    assert response.status_code == 302


def test_logout_requires_post_and_logs_out(client, customer):
    client.force_login(customer)

    assert client.get(reverse('accounts:logout')).status_code == 405
    assert is_logged_in(client)

    response = client.post(reverse('accounts:logout'))
    assert response.status_code == 302
    assert response.url == reverse('home')
    assert not is_logged_in(client)


def test_backend_does_not_return_inactive_users(make_user, password):
    make_user('pending', is_active=False, is_approved=False)
    assert EmailOrUsernameBackend().authenticate(None, username='pending', password=password) is None


# ---------------------------------------------------------------- profile


def test_profile_requires_login(client):
    response = client.get(reverse('accounts:profile'))
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={reverse('accounts:profile')}"


def test_profile_page_shows_current_details(client, customer):
    client.force_login(customer)
    response = client.get(reverse('accounts:profile'))
    assert response.status_code == 200
    assert response.context['form'].instance == customer


def test_user_can_update_profile(client, customer):
    client.force_login(customer)

    response = client.post(reverse('accounts:profile'), {
        'first_name': 'Casey', 'last_name': 'Jones', 'email': customer.email, 'phone': '+64 21 555 1234',
    })

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.last_name == 'Jones'
    assert customer.phone == '+64 21 555 1234'
    assert customer.is_approved
    assert mail.outbox == []


def test_profile_rejects_email_used_by_someone_else(client, customer, mechanic):
    client.force_login(customer)

    response = client.post(reverse('accounts:profile'), {
        'first_name': 'Casey', 'last_name': 'C', 'email': mechanic.email.upper(), 'phone': '',
    })

    assert response.status_code == 200
    assert 'email' in response.context['form'].errors
    customer.refresh_from_db()
    assert customer.email == 'customer@example.com'


def test_profile_rejects_invalid_phone(client, customer):
    client.force_login(customer)
    response = client.post(reverse('accounts:profile'), {
        'first_name': 'Casey', 'last_name': 'C', 'email': customer.email, 'phone': 'abc',
    })
    assert 'phone' in response.context['form'].errors


def test_changing_email_does_not_require_verification(client, customer):
    client.force_login(customer)

    client.post(reverse('accounts:profile'), {
        'first_name': 'Casey', 'last_name': 'C', 'email': 'changed@example.com', 'phone': '',
    })

    customer.refresh_from_db()
    assert customer.email == 'changed@example.com'
    assert customer.is_approved
    assert customer.is_active
    assert mail.outbox == []


def test_profile_cannot_change_role_or_username(client, customer):
    client.force_login(customer)

    client.post(reverse('accounts:profile'), {
        'first_name': 'Casey', 'last_name': 'C', 'email': customer.email, 'phone': '',
        'role': 'ADMIN', 'username': 'hacker', 'is_staff': 'on', 'is_superuser': 'on',
    })

    customer.refresh_from_db()
    assert customer.role == User.Role.CUSTOMER
    assert customer.username == 'customer'
    assert not customer.is_staff
    assert not customer.is_superuser


def test_profile_edits_only_affect_the_logged_in_user(client, customer, mechanic):
    client.force_login(customer)

    client.post(reverse('accounts:profile'), {
        'first_name': 'Changed', 'last_name': 'Name', 'email': customer.email, 'phone': '',
    })

    mechanic.refresh_from_db()
    assert mechanic.first_name != 'Changed'


# ---------------------------------------------------------------- password reset


def test_password_reset_sends_email_for_active_account(client, customer):
    response = client.post(reverse('accounts:password_reset'), {'email': 'customer@example.com'})

    assert response.status_code == 302
    assert response.url == reverse('accounts:password_reset_done')
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ['customer@example.com']
    assert '/accounts/password-reset/confirm/' in mail.outbox[0].body


def test_password_reset_does_not_reveal_unknown_emails(client, db):
    response = client.post(reverse('accounts:password_reset'), {'email': 'nobody@example.com'})

    assert response.status_code == 302
    assert response.url == reverse('accounts:password_reset_done')
    assert mail.outbox == []


def test_password_reset_full_flow(client, customer):
    client.post(reverse('accounts:password_reset'), {'email': 'customer@example.com'})
    link = link_from_email(mail.outbox[0], '/accounts/password-reset/confirm/')

    form_page = client.get(link)  # Django swaps the token for a session and redirects
    assert form_page.status_code == 302
    response = client.post(form_page.url, {'new_password1': 'Brand-New-Pass-99', 'new_password2': 'Brand-New-Pass-99'})

    assert response.status_code == 302
    assert response.url == reverse('accounts:password_reset_complete')
    login = client.post(reverse('accounts:login'), {'username': 'customer', 'password': 'Brand-New-Pass-99'})
    assert login.status_code == 302
    assert is_logged_in(client)


def test_password_reset_with_bad_link_shows_friendly_page(client, db):
    response = client.get(reverse('accounts:password_reset_confirm', kwargs={'uidb64': 'abc', 'token': 'def-123'}), follow=True)
    assert response.status_code == 200
    assert "isn't valid" in response.content.decode()


# ---------------------------------------------------------------- seed command


def test_seed_demo_users_refuses_when_debug_is_off(db, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command('seed_demo_users')
    assert User.objects.count() == 0


def test_seed_demo_users_creates_users_and_is_repeatable(db, settings, client):
    settings.DEBUG = True

    call_command('seed_demo_users')
    call_command('seed_demo_users')

    assert User.objects.count() == 6
    assert Workshop.objects.count() == 3
    assert Vehicle.objects.count() == 2
    assert User.objects.get(username='mechanic1').workshop != User.objects.get(username='mechanic2').workshop
    assert User.objects.filter(role=User.Role.ADMIN).count() == 1
    assert User.objects.filter(role=User.Role.MECHANIC).count() == 3
    assert User.objects.filter(role=User.Role.CUSTOMER).count() == 2
    assert client.login(username='mechanic1', password='GarageLog-demo-1')


def test_seed_demo_users_creates_the_parts_warehouse_and_its_staff(db, settings):
    settings.DEBUG = True

    call_command('seed_demo_users')

    warehouse = Workshop.get_warehouse()
    assert warehouse.name == 'Parts Warehouse'
    assert Workshop.objects.filter(is_parts_warehouse=True).count() == 1
    assert User.objects.get(username='warehouse1').workshop == warehouse
    assert not Workshop.objects.bookable().filter(pk=warehouse.pk).exists()


def test_seed_demo_users_reuses_an_existing_warehouse_whatever_it_is_called(db, settings):
    settings.DEBUG = True
    existing = Workshop.objects.create(name='Our Central Store', is_parts_warehouse=True)

    call_command('seed_demo_users')

    assert Workshop.objects.filter(is_parts_warehouse=True).count() == 1
    assert not Workshop.objects.filter(name='Parts Warehouse').exists()
    assert User.objects.get(username='warehouse1').workshop == existing
