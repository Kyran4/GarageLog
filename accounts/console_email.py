from django.core.mail.backends.console import EmailBackend as DjangoConsoleEmailBackend


class ReadableConsoleEmailBackend(DjangoConsoleEmailBackend):
    """Development email backend that prints the plain text of each email.

    Django's own console backend prints the raw MIME message. Long lines in it are wrapped
    with "=" signs (quoted-printable), which splits verification and password reset links
    across lines so they stop working when copied. This backend prints the readable body, so
    every link stays on one line. Real sending (the SMTP backend) is not affected.
    """

    def write_message(self, message):
        recipients = ', '.join(message.to)
        self.stream.write(
            f'From: {message.from_email}\n'
            f'To: {recipients}\n'
            f'Subject: {message.subject}\n'
            f'\n'
            f'{message.body}\n'
        )
        self.stream.write('-' * 79 + '\n')
