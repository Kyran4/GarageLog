import datetime

from django.core.exceptions import ValidationError
from django.db import models

WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


class Workshop(models.Model):
    """A workshop that takes bookings. Mechanics belong to one workshop; parts stock is kept per workshop."""

    name = models.CharField(max_length=100, unique=True)
    address = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    open_time = models.TimeField(default=datetime.time(8, 0))
    close_time = models.TimeField(default=datetime.time(17, 0))
    open_saturday = models.BooleanField(default=False)
    open_sunday = models.BooleanField(default=False)
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive workshops cannot be chosen for new bookings.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.open_time and self.close_time and not self.slot_starts():
            raise ValidationError('The closing time must leave room for at least one booking after opening time.')

    # ----------------------------------------------------------- opening hours

    def is_open_on(self, date):
        weekday = date.weekday()
        if weekday < 5:
            return True
        return self.open_saturday if weekday == 5 else self.open_sunday

    @property
    def open_days_text(self):
        if self.open_saturday and self.open_sunday:
            return 'Monday to Sunday'
        if self.open_saturday:
            return 'Monday to Saturday'
        if self.open_sunday:
            return 'Monday to Friday and Sunday'
        return 'Monday to Friday'

    def slot_starts(self):
        """Every booking start time, from opening time while a whole slot still fits before closing."""
        from bookings.scheduling import SLOT_MINUTES

        today = datetime.date.today()
        step = datetime.timedelta(minutes=SLOT_MINUTES)
        current = datetime.datetime.combine(today, self.open_time)
        closing = datetime.datetime.combine(today, self.close_time)
        starts = []
        while current + step <= closing:
            starts.append(current.time())
            current += step
        return starts

    @property
    def hours_text(self):
        from bookings.scheduling import format_time

        return f'{self.open_days_text}, {format_time(self.open_time)} to {format_time(self.close_time)}'
