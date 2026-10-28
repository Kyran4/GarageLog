"""Slot rules for bookings.

Bookings are fixed-length slots. Each workshop sets its own opening and closing time and
whether it opens on weekends (see the Workshop model), so two bookings at the same workshop
clash when they have the same date and start time. SLOT_MINUTES is shared by every workshop.
"""
import datetime

from django.utils import timezone

SLOT_MINUTES = 60


def format_time(value):
    """8:00 am style, without relying on platform-specific strftime codes."""
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'am' if value.hour < 12 else 'pm'}"


def slot_choices(workshop):
    """(value, label) pairs for every start time at one workshop."""
    return [(start.strftime('%H:%M'), format_time(start)) for start in workshop.slot_starts()]


def all_slot_choices(workshops):
    """Every start time any of the given workshops offers, earliest first."""
    starts = sorted({start for workshop in workshops for start in workshop.slot_starts()})
    return [(start.strftime('%H:%M'), format_time(start)) for start in starts]


def closed_reason(workshop, date):
    """Why the workshop cannot take bookings on this date, or None if it is open."""
    if not workshop.is_open_on(date):
        return f"{workshop.name} is closed on {date.strftime('%A')}s. It is open {workshop.open_days_text}."
    return None


def starts_at(date, time):
    return timezone.make_aware(datetime.datetime.combine(date, time))


def next_open_date(workshop=None, days_ahead=1):
    """The first day at least `days_ahead` days from today that the workshop is open.

    Without a workshop this is the next weekday.
    """
    date = timezone.localdate() + datetime.timedelta(days=days_ahead)
    while (workshop.is_open_on(date) if workshop else date.weekday() < 5) is False:
        date += datetime.timedelta(days=1)
    return date


def capacity(workshop):
    """How many bookings can share a slot: one per active mechanic at the workshop, at least one."""
    from accounts.models import User

    return max(1, User.objects.filter(role=User.Role.MECHANIC, workshop=workshop, is_active=True).count())


def booked_count(workshop, date, time, exclude_pk=None):
    from .models import Booking

    return (
        Booking.objects.filter(
            workshop=workshop, booking_date=date, booking_time=time, status__in=Booking.ACTIVE_STATUSES,
        )
        .exclude(pk=exclude_pk)
        .count()
    )


def lock_capacity(workshop):
    """Serialise concurrent bookings at a workshop on databases that support row locks (PostgreSQL).

    Call inside transaction.atomic() just before the final capacity check. SQLite ignores
    the lock, which is fine for development; the database constraints on Booking still stop
    the same vehicle or mechanic being double-booked.
    """
    from accounts.models import User

    list(User.objects.select_for_update().filter(role=User.Role.MECHANIC, workshop=workshop))
