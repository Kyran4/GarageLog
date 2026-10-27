"""Opening hours and slot rules for bookings.

Change the constants below to match the workshop. Bookings are fixed-length slots, so two
bookings clash when they have the same date and start time.
"""
import datetime

from django.utils import timezone

SLOT_MINUTES = 60
OPEN_TIME = datetime.time(8, 0)
CLOSE_TIME = datetime.time(17, 0)
OPEN_WEEKDAYS = (0, 1, 2, 3, 4)  # Monday to Friday
OPEN_DAYS_TEXT = 'Monday to Friday'


def format_time(value):
    """8:00 am style, without relying on platform-specific strftime codes."""
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'am' if value.hour < 12 else 'pm'}"


def slot_starts():
    """Every start time a customer can pick, for example 8:00 am to 4:00 pm."""
    today = datetime.date.today()
    step = datetime.timedelta(minutes=SLOT_MINUTES)
    current = datetime.datetime.combine(today, OPEN_TIME)
    closing = datetime.datetime.combine(today, CLOSE_TIME)
    starts = []
    while current + step <= closing:
        starts.append(current.time())
        current += step
    return starts


def slot_choices():
    return [(start.strftime('%H:%M'), format_time(start)) for start in slot_starts()]


def closed_reason(date):
    """Why the workshop cannot take bookings on this date, or None if it is open."""
    if date.weekday() not in OPEN_WEEKDAYS:
        return f"We're closed on {date.strftime('%A')}s. We're open {OPEN_DAYS_TEXT}."
    return None


def starts_at(date, time):
    return timezone.make_aware(datetime.datetime.combine(date, time))


def next_open_date(days_ahead=1):
    """The first open day at least `days_ahead` days from today."""
    date = timezone.localdate() + datetime.timedelta(days=days_ahead)
    while date.weekday() not in OPEN_WEEKDAYS:
        date += datetime.timedelta(days=1)
    return date


def capacity():
    """How many bookings can share a slot: one per active mechanic, and at least one."""
    from accounts.models import User

    return max(1, User.objects.filter(role=User.Role.MECHANIC, is_active=True).count())


def booked_count(date, time, exclude_pk=None):
    from .models import Booking

    return (
        Booking.objects.filter(booking_date=date, booking_time=time, status__in=Booking.ACTIVE_STATUSES)
        .exclude(pk=exclude_pk)
        .count()
    )


def lock_capacity():
    """Serialise concurrent bookings on databases that support row locks (PostgreSQL).

    Call inside transaction.atomic() just before the final capacity check. SQLite ignores
    the lock, which is fine for development; the database constraints on Booking still stop
    the same vehicle or mechanic being double-booked.
    """
    from accounts.models import User

    list(User.objects.select_for_update().filter(role=User.Role.MECHANIC))
