import datetime

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import User

from . import scheduling
from .models import Booking
from .tests import frozen_now

pytestmark = pytest.mark.django_db


def book(client, booking_data, vehicle, **overrides):
    return client.post(reverse('create_booking'), booking_data(vehicle, **overrides))


# ---------------------------------------------------------------- capacity (counted per workshop)


def test_capacity_is_one_when_a_workshop_has_no_mechanics(workshop):
    assert scheduling.capacity(workshop) == 1


def test_capacity_is_one_per_active_mechanic_at_that_workshop(make_user, workshop, other_workshop):
    make_user('m1', User.Role.MECHANIC)
    make_user('m2', User.Role.MECHANIC)
    make_user('retired', User.Role.MECHANIC, is_active=False)
    make_user('elsewhere', User.Role.MECHANIC, workshop=other_workshop)
    assert scheduling.capacity(workshop) == 2
    assert scheduling.capacity(other_workshop) == 1


def test_a_full_slot_is_refused_and_another_slot_is_fine(
        client, mechanic, customer, vehicle, make_user, make_vehicle, make_booking, booking_data):
    other = make_user('sam')
    make_booking(other, make_vehicle(other, plate='SAM111'))  # one mechanic, so this fills 10:00
    client.force_login(customer)

    refused = book(client, booking_data, vehicle)
    accepted = book(client, booking_data, vehicle, booking_time='11:00')

    assert refused.status_code == 200
    assert 'fully booked' in refused.context['form'].errors['booking_time'][0]
    assert accepted.status_code == 302
    assert Booking.objects.filter(customer=customer).count() == 1


def test_a_full_workshop_does_not_block_another_workshop(
        client, mechanic, customer, vehicle, other_workshop, make_user, make_vehicle, make_booking, booking_data):
    other = make_user('sam')
    make_booking(other, make_vehicle(other, plate='SAM111'))  # Central Workshop is full at 10:00
    client.force_login(customer)

    response = book(client, booking_data, vehicle, workshop=other_workshop.pk)

    assert response.status_code == 302
    assert Booking.objects.get(customer=customer).workshop == other_workshop


def test_two_mechanics_allow_two_bookings_in_a_slot_but_not_three(
        client, make_user, make_vehicle, make_booking, booking_data):
    make_user('m1', User.Role.MECHANIC)
    make_user('m2', User.Role.MECHANIC)
    people = [make_user(name) for name in ('amy', 'ben', 'cat')]
    cars = [make_vehicle(person, plate=f'CAR{index}') for index, person in enumerate(people)]

    results = []
    for person, car in zip(people, cars):
        client.force_login(person)
        results.append(book(client, booking_data, car).status_code)

    assert results == [302, 302, 200]
    assert Booking.objects.count() == 2


def test_cancelling_frees_the_slot(
        client, mechanic, customer, vehicle, make_user, make_vehicle, make_booking, booking_data):
    other = make_user('sam')
    taken = make_booking(other, make_vehicle(other, plate='SAM111'))
    client.force_login(customer)
    assert book(client, booking_data, vehicle).status_code == 200

    taken.status = 'CANCELLED'
    taken.save()

    assert book(client, booking_data, vehicle).status_code == 302


def test_completed_bookings_do_not_block_a_slot(
        client, mechanic, customer, vehicle, make_user, make_vehicle, make_booking, booking_data):
    other = make_user('sam')
    make_booking(other, make_vehicle(other, plate='SAM111'), status='COMPLETED')
    client.force_login(customer)

    assert book(client, booking_data, vehicle).status_code == 302


def test_editing_a_booking_does_not_clash_with_itself(client, mechanic, customer, vehicle, make_booking, booking_data):
    booking = make_booking(customer, vehicle)  # the only mechanic is now fully booked at 10:00
    client.force_login(customer)

    response = client.post(
        reverse('booking_edit', kwargs={'pk': booking.pk}),
        booking_data(vehicle, notes='Just adding a note'),
    )

    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.notes == 'Just adding a note'


# ---------------------------------------------------------------- same vehicle / same mechanic


def test_same_vehicle_cannot_be_booked_twice_in_a_slot(client, make_user, customer, vehicle, make_booking, booking_data):
    make_user('m1', User.Role.MECHANIC)
    make_user('m2', User.Role.MECHANIC)  # plenty of capacity, so only the vehicle rule applies
    make_booking(customer, vehicle)
    client.force_login(customer)

    response = book(client, booking_data, vehicle)

    assert response.status_code == 200
    assert 'already has a booking' in response.context['form'].errors['vehicle'][0]


def test_same_vehicle_cannot_be_at_two_workshops_at_once(
        client, customer, vehicle, other_workshop, make_booking, booking_data):
    make_booking(customer, vehicle)  # Central Workshop, 10:00
    client.force_login(customer)

    response = book(client, booking_data, vehicle, workshop=other_workshop.pk)  # North Workshop, 10:00

    assert response.status_code == 200
    assert 'already has a booking' in response.context['form'].errors['vehicle'][0]


def test_a_mechanic_cannot_be_assigned_to_two_bookings_in_a_slot(
        client, admin_user, make_user, mechanic, customer, vehicle, make_vehicle, make_booking, booking_data):
    make_user('m2', User.Role.MECHANIC)
    other_vehicle = make_vehicle(customer, plate='SECOND1')
    make_booking(customer, vehicle, mechanic=mechanic, status='CONFIRMED')
    second = make_booking(customer, other_vehicle)
    client.force_login(admin_user)

    response = client.post(
        reverse('booking_edit', kwargs={'pk': second.pk}),
        booking_data(other_vehicle, customer=customer.pk, mechanic=mechanic.pk, status='CONFIRMED'),
    )

    assert response.status_code == 200
    assert 'mechanic is already booked' in response.content.decode()
    second.refresh_from_db()
    assert second.mechanic is None


def test_a_mechanic_cannot_be_assigned_to_another_workshops_booking(
        client, admin_user, make_user, other_workshop, customer, vehicle, make_booking, booking_data):
    northern = make_user('northern', User.Role.MECHANIC, workshop=other_workshop)
    booking = make_booking(customer, vehicle)  # at Central Workshop
    client.force_login(admin_user)

    response = client.post(
        reverse('booking_edit', kwargs={'pk': booking.pk}),
        booking_data(vehicle, customer=customer.pk, mechanic=northern.pk, status='CONFIRMED'),
    )

    assert response.status_code == 200
    assert 'works at a different workshop' in response.content.decode()
    booking.refresh_from_db()
    assert booking.mechanic is None


def test_database_refuses_a_double_booked_vehicle_even_without_the_form_checks(customer, vehicle, make_booking):
    make_booking(customer, vehicle)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_booking(customer, vehicle)


def test_database_refuses_a_double_booked_mechanic(customer, mechanic, vehicle, make_vehicle, make_booking):
    make_booking(customer, vehicle, mechanic=mechanic)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_booking(customer, make_vehicle(customer, plate='SECOND1'), mechanic=mechanic)


def test_cancelled_duplicates_are_allowed_by_the_database(customer, vehicle, make_booking):
    make_booking(customer, vehicle, status='CANCELLED')
    make_booking(customer, vehicle, status='CANCELLED')
    make_booking(customer, vehicle)

    assert Booking.objects.count() == 3


# ---------------------------------------------------------------- opening hours and times


def test_weekend_bookings_are_refused(client, customer, vehicle, booking_data, open_day):
    saturday = open_day + datetime.timedelta(days=(5 - open_day.weekday()))
    client.force_login(customer)

    response = book(client, booking_data, vehicle, booking_date=saturday.isoformat())

    assert response.status_code == 200
    assert 'closed' in response.context['form'].errors['booking_date'][0]


def test_earlier_time_today_is_refused(client, customer, vehicle, booking_data, open_day):
    client.force_login(customer)

    with frozen_now(open_day, 13):
        refused = book(client, booking_data, vehicle, booking_time='09:00')
        accepted = book(client, booking_data, vehicle, booking_time='15:00')

    assert refused.status_code == 200
    assert 'already passed' in refused.context['form'].errors['booking_time'][0]
    assert accepted.status_code == 302


def test_slot_choices_cover_opening_hours(workshop):
    labels = [label for _, label in scheduling.slot_choices(workshop)]
    assert labels[0] == '8:00 am'
    assert labels[-1] == '4:00 pm'
    assert len(labels) == 9


def test_all_slot_choices_combine_every_workshops_hours(make_workshop):
    early = make_workshop('Early', open_time=datetime.time(6, 0), close_time=datetime.time(10, 0))
    late = make_workshop('Late', open_time=datetime.time(15, 0), close_time=datetime.time(19, 0))

    labels = [label for _, label in scheduling.all_slot_choices([early, late])]

    assert labels == ['6:00 am', '7:00 am', '8:00 am', '9:00 am', '3:00 pm', '4:00 pm', '5:00 pm', '6:00 pm']


def test_next_open_date_respects_a_workshops_weekend_hours(make_workshop):
    weekdays_only = make_workshop('Weekdays')
    open_saturdays = make_workshop('Saturdays', open_saturday=True)

    assert scheduling.next_open_date(weekdays_only, days_ahead=0).weekday() < 5
    assert scheduling.next_open_date(open_saturdays, days_ahead=0).weekday() < 6


def test_booking_helpers(customer, vehicle, make_booking, open_day):
    booking = make_booking(customer, vehicle)

    assert booking.end_time == datetime.time(11, 0)
    assert booking.is_upcoming
    assert booking.can_be_edited_by(customer)
    with frozen_now(open_day, 12):
        assert not booking.is_upcoming
        assert not booking.can_be_edited_by(customer)
