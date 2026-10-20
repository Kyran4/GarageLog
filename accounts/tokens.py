from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Single-use token for verifying an email address.

    The hash includes the email and verification flag, so a link stops working
    once it has been used or once the user changes their email. Links expire
    after settings.PASSWORD_RESET_TIMEOUT (3 days by default).
    """

    key_salt = 'accounts.tokens.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{user.email}{user.email_verified}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()
