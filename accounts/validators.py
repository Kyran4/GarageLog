from django.core.validators import RegexValidator

validate_phone = RegexValidator(
    regex=r'^\+?[0-9][0-9 ()\-]{5,29}$',
    message='Enter a valid phone number, for example 021 123 4567 or +64 21 123 4567.',
)
