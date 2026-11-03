import io

import pytest
from django.core.mail import EmailMessage

from accounts.console_email import ReadableConsoleEmailBackend

pytestmark = pytest.mark.django_db


def test_console_backend_prints_long_links_unbroken():
    link = 'http://127.0.0.1:8000/accounts/password-reset/confirm/MQ/' + 'a1b2c3-' + 'f' * 60 + '/'
    stream = io.StringIO()
    backend = ReadableConsoleEmailBackend(stream=stream)

    backend.send_messages([EmailMessage('Verify', f'Open this link:\n\n{link}\n', 'noreply@example.com', ['kyran@example.com'])])

    output = stream.getvalue()
    assert link in output  # the whole link is on one line, with no "=" line breaks
    assert 'quoted-printable' not in output
    assert 'To: kyran@example.com' in output
    assert 'Subject: Verify' in output
