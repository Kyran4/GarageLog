import base64
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
from django.core.mail import EmailMessage
from django.test import override_settings

from accounts.gmail_email import GmailEmailBackend


@override_settings(
    GMAIL_CLIENT_ID='client-id',
    GMAIL_CLIENT_SECRET='client-secret',
    GMAIL_REFRESH_TOKEN='refresh-token',
    GMAIL_API_TIMEOUT=10,
)
def test_gmail_backend_refreshes_token_and_sends_mime_message():
    token_response = MagicMock()
    token_response.status = 200
    token_response.read.return_value = b'{"access_token":"access-token"}'
    token_response.__enter__.return_value = token_response
    send_response = MagicMock()
    send_response.status = 200
    send_response.read.return_value = b'{"id":"message-id"}'
    send_response.__enter__.return_value = send_response
    message = EmailMessage(
        'Reset your password',
        'Password reset link',
        'GarageLog <garage@gmail.com>',
        ['customer@example.com'],
    )

    with patch(
        'accounts.gmail_email.urlopen',
        side_effect=[token_response, send_response],
    ) as urlopen:
        sent = GmailEmailBackend().send_messages([message])

    token_request, send_request = (
        call.args[0] for call in urlopen.call_args_list
    )
    assert sent == 1
    assert token_request.full_url == 'https://oauth2.googleapis.com/token'
    assert b'grant_type=refresh_token' in token_request.data
    assert b'client_secret=client-secret' in token_request.data
    assert send_request.full_url == (
        'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
    )
    assert send_request.get_header('Authorization') == 'Bearer access-token'
    payload = json.loads(send_request.data)
    decoded_message = base64.urlsafe_b64decode(payload['raw'])
    assert b'Subject: Reset your password' in decoded_message
    assert b'To: customer@example.com' in decoded_message
    assert b'Password reset link' in decoded_message
    assert urlopen.call_count == 2


@override_settings(
    GMAIL_CLIENT_ID='',
    GMAIL_CLIENT_SECRET='client-secret',
    GMAIL_REFRESH_TOKEN='refresh-token',
)
def test_gmail_backend_requires_oauth_credentials():
    with pytest.raises(RuntimeError, match='GMAIL_CLIENT_ID'):
        GmailEmailBackend().send_messages([
            EmailMessage('Subject', 'Body', 'from@example.com', ['to@example.com'])
        ])


@override_settings(
    GMAIL_CLIENT_ID='client-id',
    GMAIL_CLIENT_SECRET='client-secret',
    GMAIL_REFRESH_TOKEN='refresh-token',
)
def test_gmail_backend_reports_token_endpoint_errors():
    error = HTTPError(
        'https://oauth2.googleapis.com/token',
        401,
        'Unauthorized',
        {},
        None,
    )
    with patch('accounts.gmail_email.urlopen', side_effect=error):
        with pytest.raises(RuntimeError, match='HTTP 401'):
            GmailEmailBackend().send_messages([
                EmailMessage('Subject', 'Body', 'from@example.com', ['to@example.com'])
            ])
