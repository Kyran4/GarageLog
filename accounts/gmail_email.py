import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class GmailEmailBackend(BaseEmailBackend):
    """Send Django email messages through the Gmail API."""

    token_url = 'https://oauth2.googleapis.com/token'
    send_url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(**kwargs)
        self.fail_silently = fail_silently

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        credentials = {
            'GMAIL_CLIENT_ID': getattr(settings, 'GMAIL_CLIENT_ID', ''),
            'GMAIL_CLIENT_SECRET': getattr(settings, 'GMAIL_CLIENT_SECRET', ''),
            'GMAIL_REFRESH_TOKEN': getattr(settings, 'GMAIL_REFRESH_TOKEN', ''),
        }
        missing = [name for name, value in credentials.items() if not value]
        if missing:
            raise RuntimeError(
                f'Gmail API credentials are missing: {", ".join(missing)}.'
            )

        sent = 0
        access_token = None
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                if access_token is None:
                    access_token = self._get_access_token(credentials)
                self._send_message(message, access_token)
            except RuntimeError:
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent

    def _get_access_token(self, credentials):
        data = urlencode({
            'client_id': credentials['GMAIL_CLIENT_ID'],
            'client_secret': credentials['GMAIL_CLIENT_SECRET'],
            'refresh_token': credentials['GMAIL_REFRESH_TOKEN'],
            'grant_type': 'refresh_token',
        }).encode('ascii')
        request = Request(
            self.token_url,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        response = self._request_json(request)
        access_token = response.get('access_token')
        if not access_token:
            raise RuntimeError('Google OAuth response did not include an access token.')
        return access_token

    def _send_message(self, message, access_token):
        mime_message = message.message()
        raw_message = base64.urlsafe_b64encode(
            mime_message.as_bytes()
        ).decode('ascii')
        data = json.dumps({'raw': raw_message}).encode('utf-8')
        request = Request(
            self.send_url,
            data=data,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        self._request_json(request)

    def _request_json(self, request):
        try:
            with urlopen(request, timeout=settings.GMAIL_API_TIMEOUT) as response:
                status = response.status
                body = response.read()
        except HTTPError as error:
            detail = error.read().decode('utf-8', errors='replace')
            raise RuntimeError(
                f'Google email API request failed with HTTP {error.code}: {detail}'
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f'Google email API request failed: {error}') from error

        if not 200 <= status < 300:
            raise RuntimeError(f'Google email API request failed with HTTP {status}.')
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as error:
            raise RuntimeError('Google email API returned an invalid JSON response.') from error
