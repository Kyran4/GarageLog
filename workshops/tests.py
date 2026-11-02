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


# ---------------------------------------------------------------- the parts warehouse


def test_a_location_is_a_normal_workshop_unless_marked_as_the_warehouse(workshop):
    assert not workshop.is_parts_warehouse
    assert workshop.accepts_bookings


def test_the_warehouse_does_not_accept_bookings(warehouse):
    assert warehouse.is_parts_warehouse
    assert not warehouse.accepts_bookings


def test_inactive_workshops_do_not_accept_bookings(make_workshop):
    assert not make_workshop('Closed', is_active=False).accepts_bookings


def test_bookable_leaves_out_the_warehouse_and_inactive_workshops(workshop, other_workshop, warehouse, make_workshop):
    make_workshop('Closed', is_active=False)

    assert set(Workshop.objects.bookable()) == {workshop, other_workshop}


def test_get_warehouse_returns_it_or_none(workshop):
    assert Workshop.get_warehouse() is None
    shed = Workshop.objects.create(name='Shed', is_parts_warehouse=True)
    assert Workshop.get_warehouse() == shed


def test_there_can_only_be_one_warehouse(warehouse):
    second = Workshop(name='Second Store', is_parts_warehouse=True)
    with pytest.raises(ValidationError) as error:
        second.full_clean()
    assert 'Parts Warehouse is already the parts warehouse' in str(error.value)

    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        Workshop.objects.create(name='Second Store', is_parts_warehouse=True)


def test_the_warehouse_can_be_edited_without_tripping_the_one_warehouse_rule(warehouse):
    warehouse.phone = '09 555 0000'
    warehouse.full_clean()
    warehouse.save()


def test_several_ordinary_workshops_are_fine(workshop, other_workshop):
    assert Workshop.objects.filter(is_parts_warehouse=False).count() == 2


# ---------------------------------------------------------------- the migration's guess at an existing warehouse


def flag(*names):
    from importlib import import_module

    from django.apps import apps

    for name in names:
        Workshop.objects.create(name=name)
    import_module('workshops.migrations.0002_parts_warehouse').flag_existing_warehouse(apps, None)
    return sorted(Workshop.objects.filter(is_parts_warehouse=True).values_list('name', flat=True))


@pytest.mark.parametrize('name', ['Parts Warehouse', 'Main Warehouse', 'warehouse', 'Penrose WAREHOUSE'])
def test_a_single_location_called_a_warehouse_is_flagged(name):
    assert flag('Auckland Central', name) == [name]


def test_nothing_is_flagged_when_no_name_mentions_a_warehouse():
    assert flag('Main Workshop', 'North Shore') == []


def test_nothing_is_flagged_when_it_is_unclear_which_is_the_warehouse():
    assert flag('East Warehouse', 'West Warehouse') == []
