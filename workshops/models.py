import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


class WorkshopQuerySet(models.QuerySet):
    def bookable(self):
        """Locations customers can book: active, and not the parts warehouse."""
        return self.filter(is_active=True, is_parts_warehouse=False)


class Workshop(models.Model):
    """A location that holds parts stock and has staff. Most are workshops that take bookings.

    One location can be marked as the parts warehouse: the central store that supplies the
    workshops. It holds stock but does not take customer bookings.
    """

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
    is_parts_warehouse = models.BooleanField(
        'parts warehouse',
        default=False,
        help_text=(
            'The central parts warehouse. It holds parts stock that workshops can check, and it does not '
            'take customer bookings. Only one location can be the parts warehouse.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkshopQuerySet.as_manager()

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['is_parts_warehouse'],
                condition=Q(is_parts_warehouse=True),
                name='single_parts_warehouse',
                violation_error_message='There is already a parts warehouse.',
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.open_time and self.close_time and not self.slot_starts():
            raise ValidationError('The closing time must leave room for at least one booking after opening time.')
        if self.is_parts_warehouse:
            other = Workshop.objects.filter(is_parts_warehouse=True).exclude(pk=self.pk).first()
            if other:
                raise ValidationError({'is_parts_warehouse': f'{other.name} is already the parts warehouse.'})

    @classmethod
    def get_warehouse(cls):
        """The parts warehouse, or None if there isn't one."""
        return cls.objects.filter(is_parts_warehouse=True).first()

    @property
    def accepts_bookings(self):
        return self.is_active and not self.is_parts_warehouse

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
