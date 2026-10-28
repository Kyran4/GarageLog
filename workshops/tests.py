import datetime

import pytest
from django.core.exceptions import ValidationError

from workshops.models import Workshop

pytestmark = pytest.mark.django_db


def test_default_hours_are_monday_to_friday_8_to_5(workshop):
    assert workshop.hours_text == 'Monday to Friday, 8:00 am to 5:00 pm'
    starts = workshop.slot_starts()
    assert starts[0] == datetime.time(8, 0)
    assert starts[-1] == datetime.time(16, 0)  # the last booking has to finish by closing time
    assert len(starts) == 9


@pytest.mark.parametrize('saturday, sunday, text', [
    (False, False, 'Monday to Friday'),
    (True, False, 'Monday to Saturday'),
    (False, True, 'Monday to Friday and Sunday'),
    (True, True, 'Monday to Sunday'),
])
def test_open_days_text(make_workshop, saturday, sunday, text):
    shop = make_workshop('Shop', open_saturday=saturday, open_sunday=sunday)
    assert shop.open_days_text == text


def test_is_open_on(make_workshop):
    monday = datetime.date(2026, 11, 2)
    saturday = datetime.date(2026, 11, 7)
    sunday = datetime.date(2026, 11, 8)
    weekdays = make_workshop('Weekdays')
    saturdays = make_workshop('Saturdays', open_saturday=True)

    assert weekdays.is_open_on(monday)
    assert not weekdays.is_open_on(saturday) and not weekdays.is_open_on(sunday)
    assert saturdays.is_open_on(saturday) and not saturdays.is_open_on(sunday)


def test_hours_must_leave_room_for_a_booking():
    shop = Workshop(name='Tiny', open_time=datetime.time(9, 0), close_time=datetime.time(9, 30))
    with pytest.raises(ValidationError):
        shop.full_clean()
    shop.close_time = datetime.time(10, 0)
    shop.full_clean()


def test_closing_before_opening_is_invalid():
    shop = Workshop(name='Backwards', open_time=datetime.time(17, 0), close_time=datetime.time(8, 0))
    with pytest.raises(ValidationError):
        shop.full_clean()


def test_workshop_names_are_unique(workshop):
    with pytest.raises(ValidationError):
        Workshop(name=workshop.name).full_clean()


def test_str_is_the_name(workshop):
    assert str(workshop) == 'Central Workshop'
