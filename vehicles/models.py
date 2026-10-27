import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

EXPIRY_WARNING_DAYS = 30

validate_plate = RegexValidator(
    regex=r'^[A-Za-z0-9 ]{1,8}$',
    message='Enter a number plate using letters and numbers only, for example ABC123.',
)


def validate_year(value):
    latest = timezone.localdate().year + 1
    if value < 1900 or value > latest:
        raise ValidationError(f'Enter a year between 1900 and {latest}.')


def normalize_plate(value):
    return re.sub(r'\s+', '', value or '').upper()


def expiry_status(expiry):
    """Return 'expired', 'soon' (within 30 days) or 'ok'; None when there is no date."""
    if expiry is None:
        return None
    days_left = (expiry - timezone.localdate()).days
    if days_left < 0:
        return 'expired'
    if days_left <= EXPIRY_WARNING_DAYS:
        return 'soon'
    return 'ok'


class Vehicle(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vehicles',
    )
    plate = models.CharField(
        'number plate', max_length=8, unique=True, validators=[validate_plate],
    )
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    year = models.PositiveSmallIntegerField(validators=[validate_year])
    wof_expiry = models.DateField('WoF expiry', null=True, blank=True)
    rego_expiry = models.DateField('registration expiry', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['plate']

    def __str__(self):
        return f'{self.plate} - {self.year} {self.make} {self.model}'

    def save(self, *args, **kwargs):
        self.plate = normalize_plate(self.plate)
        super().save(*args, **kwargs)

    @property
    def wof_status(self):
        return expiry_status(self.wof_expiry)

    @property
    def rego_status(self):
        return expiry_status(self.rego_expiry)
