import io

import pytest
from django.core.mail import EmailMessage
from django.urls import reverse

from accounts.console_email import ReadableConsoleEmailBackend
from accounts.models import User

pytestmark = pytest.mark.django_db


def test_console_backend_prints_long_links_unbroken():
    link = 'http://127.0.0.1:8000/accounts/verify/MQ/' + 'a1b2c3-' + 'f' * 60 + '/'
    stream = io.StringIO()
    backend = ReadableConsoleEmailBackend(stream=stream)

    backend.send_messages([EmailMessage('Verify', f'Open this link:\n\n{link}\n', 'noreply@example.com', ['kyran@example.com'])])

    output = stream.getvalue()
    assert link in output  # the whole link is on one line, with no "=" line breaks
    assert 'quoted-printable' not in output
    assert 'To: kyran@example.com' in output
    assert 'Subject: Verify' in output


def test_signup_verification_link_printed_to_console_works(client, settings):
    settings.EMAIL_BACKEND = 'accounts.console_email.ReadableConsoleEmailBackend'
    stream = io.StringIO()

    from unittest import mock
    with mock.patch('sys.stdout', stream):
        client.post(reverse('accounts:signup'), {
            'username': 'newcustomer', 'email': 'new@example.com', 'first_name': 'New', 'last_name': 'Customer',
            'phone': '', 'password1': 'Str0ng-Passw0rd!', 'password2': 'Str0ng-Passw0rd!',
        }, HTTP_HOST='127.0.0.1:8000')

    printed = stream.getvalue()
    line = next(text for text in printed.splitlines() if '/accounts/verify/' in text)
    path = line.strip().split('127.0.0.1:8000', 1)[1]

    response = client.get(path)

    assert response.status_code == 302
    assert response.url == reverse('accounts:login')
    assert User.objects.get(username='newcustomer').is_active
