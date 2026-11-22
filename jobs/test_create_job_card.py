"""Tests for creating a job card from a booking (the button on the booking list and booking page)."""
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.shortcuts import resolve_url
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.models import BookingQuoteLabour, BookingQuotePart
from jobs.models import JobCard, JobPart


def create_url(booking):
    return reverse('jobcard_create', args=[booking.pk])


def booking_url(booking):
    return reverse('booking_detail', args=[booking.pk])


def message_texts(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


@pytest.fixture
def confirmed_booking(customer, vehicle, make_booking, mechanic):
    """A confirmed booking at the default workshop, assigned to `mechanic`."""
    return make_booking(customer, vehicle, status='CONFIRMED', mechanic=mechanic)


# ---------------------------------------------------------------- who can create one

def test_admin_creates_a_job_card_for_the_bookings_mechanic(client, admin_user, confirmed_booking, mechanic):
    client.force_login(admin_user)

    response = client.post(create_url(confirmed_booking))

    job_card = JobCard.objects.get(booking=confirmed_booking)
    assert job_card.mechanic == mechanic
    assert response.status_code == 302
    assert response.url == reverse('jobcard_detail', args=[job_card.pk])
    assert 'The job card has been created.' in message_texts(response)


def test_mechanic_takes_a_booking_that_has_no_mechanic(client, mechanic, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle, status='CONFIRMED')
    client.force_login(mechanic)

    response = client.post(create_url(booking))

    job_card = JobCard.objects.get(booking=booking)
    assert job_card.mechanic == mechanic
    assert response.url == reverse('jobcard_detail', args=[job_card.pk])


def test_colleague_creating_a_job_card_keeps_the_bookings_mechanic(client, make_user, confirmed_booking, mechanic):
    colleague = make_user('colleague', User.Role.MECHANIC)
    client.force_login(colleague)

    response = client.post(create_url(confirmed_booking))

    assert JobCard.objects.get(booking=confirmed_booking).mechanic == mechanic
    assert response.url == booking_url(confirmed_booking)


def test_mechanic_at_another_workshop_cannot_create_a_job_card(client, make_user, other_workshop, confirmed_booking):
    outsider = make_user('outsider', User.Role.MECHANIC, workshop=other_workshop)
    client.force_login(outsider)

    response = client.post(create_url(confirmed_booking))

    assert response.status_code == 404
    assert not JobCard.objects.exists()


def test_customer_cannot_create_a_job_card(client, customer, confirmed_booking):
    client.force_login(customer)

    response = client.post(create_url(confirmed_booking))

    assert response.status_code == 403
    assert not JobCard.objects.exists()


def test_logged_out_visitor_is_sent_to_log_in(client, confirmed_booking):
    response = client.post(create_url(confirmed_booking))

    assert response.status_code == 302
    assert response.url.startswith(resolve_url(settings.LOGIN_URL))
    assert not JobCard.objects.exists()


def test_creating_a_job_card_needs_a_button_press_not_a_page_visit(client, admin_user, confirmed_booking):
    client.force_login(admin_user)

    response = client.get(create_url(confirmed_booking))

    assert response.status_code == 405
    assert not JobCard.objects.exists()


# ---------------------------------------------------------------- which bookings can have one

@pytest.mark.parametrize('status', ['CONFIRMED', 'IN_PROGRESS'])
def test_confirmed_and_in_progress_bookings_can_have_a_job_card(
        client, admin_user, customer, vehicle, make_booking, mechanic, status):
    booking = make_booking(customer, vehicle, status=status, mechanic=mechanic)
    client.force_login(admin_user)

    client.post(create_url(booking))

    assert JobCard.objects.filter(booking=booking).exists()


@pytest.mark.parametrize('status', ['PENDING', 'CANCELLED', 'COMPLETED'])
def test_other_bookings_cannot_have_a_job_card(
        client, admin_user, customer, vehicle, make_booking, mechanic, status):
    booking = make_booking(customer, vehicle, status=status, mechanic=mechanic)
    client.force_login(admin_user)

    response = client.post(create_url(booking))

    assert not JobCard.objects.filter(booking=booking).exists()
    assert response.url == booking_url(booking)
    assert any('Only confirmed' in text for text in message_texts(response))


def test_admin_must_assign_a_mechanic_first(client, admin_user, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle, status='CONFIRMED')
    client.force_login(admin_user)

    response = client.post(create_url(booking))

    assert not JobCard.objects.filter(booking=booking).exists()
    assert response.url == booking_url(booking)
    assert any('Assign a mechanic' in text for text in message_texts(response))


def test_booking_at_the_parts_warehouse_gets_no_job_card(
        client, admin_user, customer, vehicle, make_booking, warehouse, warehouse_staff):
    booking = make_booking(customer, vehicle, status='CONFIRMED', mechanic=warehouse_staff, workshop=warehouse)
    client.force_login(admin_user)

    response = client.post(create_url(booking))

    assert not JobCard.objects.filter(booking=booking).exists()
    assert response.url == booking_url(booking)
    assert any('parts warehouse' in text for text in message_texts(response))


def test_a_booking_cannot_get_a_second_job_card(client, admin_user, confirmed_booking):
    client.force_login(admin_user)
    client.post(create_url(confirmed_booking))

    response = client.post(create_url(confirmed_booking))

    assert JobCard.objects.filter(booking=confirmed_booking).count() == 1
    assert response.url == booking_url(confirmed_booking)
    assert any('already has a job card' in text for text in message_texts(response))


def test_job_card_creation_transfers_accepted_quote_once(
        client, admin_user, confirmed_booking, mechanic, make_part, make_stock):
    part = make_part(name="Oil filter")
    stock = make_stock(mechanic.workshop, part, quantity=5, unit_cost="8.00")
    BookingQuotePart.objects.create(
        booking=confirmed_booking,
        stock_item=stock,
        quantity=2,
        unit_price="19.95",
    )
    BookingQuoteLabour.objects.create(
        booking=confirmed_booking,
        description="Replace filter",
        charge="90.00",
    )
    BookingQuoteLabour.objects.create(
        booking=confirmed_booking,
        description="Inspect engine",
        charge="25.00",
    )
    confirmed_booking.quote_accepted_at = timezone.now()
    confirmed_booking.save(update_fields=["quote_accepted_at"])
    stock.refresh_from_db()
    assert stock.quantity == 5
    client.force_login(admin_user)

    response = client.post(create_url(confirmed_booking))

    job_card = JobCard.objects.get(booking=confirmed_booking)
    job_part = job_card.parts.get()
    stock.refresh_from_db()
    assert response.url == reverse('jobcard_detail', args=[job_card.pk])
    assert job_part.stock_item == stock
    assert job_part.part == part
    assert job_part.name == part.name
    assert job_part.quantity == 2
    assert job_part.unit_price == Decimal("19.95")
    assert job_part.source == JobPart.Source.WORKSHOP
    assert job_part.supply_status == JobPart.SupplyStatus.READY
    assert job_card.labor_charge == Decimal("115.00")
    assert stock.quantity == 3

    response = client.post(create_url(confirmed_booking))

    stock.refresh_from_db()
    assert response.url == booking_url(confirmed_booking)
    assert job_card.parts.count() == 1
    assert stock.quantity == 3


def test_job_card_does_not_transfer_an_unaccepted_quote(
        client, admin_user, confirmed_booking, mechanic, make_part, make_stock):
    part = make_part(name="Oil filter")
    stock = make_stock(mechanic.workshop, part, quantity=5)
    BookingQuotePart.objects.create(
        booking=confirmed_booking,
        stock_item=stock,
        quantity=2,
        unit_price="19.95",
    )
    BookingQuoteLabour.objects.create(
        booking=confirmed_booking,
        description="Replace filter",
        charge="90.00",
    )
    client.force_login(admin_user)

    client.post(create_url(confirmed_booking))

    job_card = JobCard.objects.get(booking=confirmed_booking)
    stock.refresh_from_db()
    assert not job_card.parts.exists()
    assert job_card.labor_charge == Decimal("0.00")
    assert stock.quantity == 5


# ---------------------------------------------------------------- the buttons on the booking pages

def test_booking_page_shows_the_create_button_to_staff_only(client, admin_user, customer, confirmed_booking):
    page = booking_url(confirmed_booking)

    client.force_login(admin_user)
    assert create_url(confirmed_booking) in client.get(page).content.decode()

    client.force_login(customer)
    assert create_url(confirmed_booking) not in client.get(page).content.decode()


def test_booking_page_links_to_the_job_card_once_it_exists(client, admin_user, confirmed_booking):
    client.force_login(admin_user)
    client.post(create_url(confirmed_booking))
    job_card = JobCard.objects.get(booking=confirmed_booking)

    body = client.get(booking_url(confirmed_booking)).content.decode()

    assert reverse('jobcard_detail', args=[job_card.pk]) in body
    assert create_url(confirmed_booking) not in body


def test_booking_page_has_no_create_button_for_a_pending_booking(client, admin_user, customer, vehicle, make_booking,
                                                                 mechanic):
    booking = make_booking(customer, vehicle, status='PENDING', mechanic=mechanic)
    client.force_login(admin_user)

    body = client.get(booking_url(booking)).content.decode()

    assert create_url(booking) not in body


def test_booking_page_has_no_create_button_at_the_parts_warehouse(
        client, admin_user, customer, vehicle, make_booking, warehouse, warehouse_staff):
    booking = make_booking(customer, vehicle, status='CONFIRMED', mechanic=warehouse_staff, workshop=warehouse)
    client.force_login(admin_user)

    body = client.get(booking_url(booking)).content.decode()

    assert create_url(booking) not in body


def test_booking_list_shows_the_create_button_to_staff_only(client, admin_user, mechanic, customer, confirmed_booking):
    page = reverse('booking_list')

    client.force_login(admin_user)
    assert create_url(confirmed_booking) in client.get(page).content.decode()

    client.force_login(mechanic)
    assert create_url(confirmed_booking) in client.get(page).content.decode()

    client.force_login(customer)
    assert create_url(confirmed_booking) not in client.get(page).content.decode()