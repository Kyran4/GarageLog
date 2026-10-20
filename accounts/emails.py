import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token

logger = logging.getLogger(__name__)


def build_verification_url(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    path = reverse('accounts:verify_email', kwargs={'uidb64': uid, 'token': token})
    return request.build_absolute_uri(path)


def send_verification_email(request, user):
    """Email a verification link. Returns True if the email was handed off."""
    context = {'user': user, 'verify_url': build_verification_url(request, user)}
    subject = render_to_string('accounts/email/verify_subject.txt', context)
    subject = ''.join(subject.splitlines()).strip()
    body = render_to_string('accounts/email/verify_email.txt', context)
    try:
        send_mail(subject, body, None, [user.email])
    except Exception:
        logger.exception('Could not send verification email to user %s', user.pk)
        return False
    return True
