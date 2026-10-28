import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking

from .models import Vehicle, expiry_status, normalize_plate, validate_year

pytestmark = pytest.mark.django_db

VEHICLE_DATA = {
    'plate': 'abc 123', 'make': 'Toyota', 'model': 'Corolla', 'year': '2015',
    'wof_expiry': '', 'rego_expiry': '',
}


# ---------------------------------------------------------------- model


def test_plate_is_stored_upper_case_without_spaces(customer):
    vehicle = Vehicle.objects.create(owner=customer, plate=' ab c 12 ', make='Mazda', model='3', year=2018)
    assert vehicle.plate == 'ABC12'
    assert normalize_plate('xy 1 z') == 'XY1Z'


def test_plate_must_be_unique(customer, make_vehicle):
    make_vehicle(customer, plate='ABC123')
    with pytest.raises(IntegrityError), transaction.atomic():
        make_vehicle(customer, plate='abc123')


@pytest.mark.parametrize('year, valid', [(1899, False), (1900, True), (2015, True), (3000, False)])
def test_year_validation(year, valid):
    if valid:
        validate_year(year)
    else:
        with pytest.raises(ValidationError):
            validate_year(year)


def test_expiry_status():
    today = timezone.localdate()
    assert expiry_status(None) is None
    assert expiry_status(today - datetime.timedelta(days=1)) == 'expired'
    assert expiry_status(today) == 'soon'
    assert expiry_status(today + datetime.timedelta(days=30)) == 'soon'
    assert expiry_status(today + datetime.timedelta(days=31)) == 'ok'


def test_vehicle_str(vehicle):
    assert str(vehicle) == 'ABC123 - 2015 Toyota Corolla'


# ---------------------------------------------------------------- access


@pytest.mark.parametrize('url_name, needs_pk', [
    ('vehicles:list', False), ('vehicles:create', False), ('vehicles:detail', True),
    ('vehicles:edit', True), ('vehicles:delete', True),
])
def test_anonymous_users_are_sent_to_login(client, vehicle, url_name, needs_pk):
    url = reverse(url_name, kwargs={'pk': vehicle.pk} if needs_pk else {})
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={url}"


@pytest.mark.parametrize('url_name, needs_pk', [
    ('vehicles:create', False), ('vehicles:edit', True), ('vehicles:delete', True),
])
def test_mechanics_cannot_add_edit_or_delete_vehicles(client, mechanic, vehicle, url_name, needs_pk):
    client.force_login(mechanic)
    url = reverse(url_name, kwargs={'pk': vehicle.pk} if needs_pk else {})

    assert client.get(url).status_code == 403
    assert client.post(url, {**VEHICLE_DATA, 'plate': vehicle.plate, 'make': 'Hacked'}).status_code == 403
    vehicle.refresh_from_db()
    assert vehicle.make == 'Toyota'



def test_customer_only_sees_their_own_vehicles(client, customer, vehicle, make_user, make_vehicle):
    other = make_user('sam')
    theirs = make_vehicle(other, plate='SAM111')
    client.force_login(customer)

    response = client.get(reverse('vehicles:list'))

    assert list(response.context['vehicles']) == [vehicle]
    assert 'SAM111' not in response.content.decode()
    for url_name in ('vehicles:detail', 'vehicles:edit', 'vehicles:delete'):
        assert client.get(reverse(url_name, kwargs={'pk': theirs.pk})).status_code == 404


def test_customer_cannot_change_or_delete_someone_elses_vehicle(client, customer, make_user, make_vehicle):
    other = make_user('sam')
    theirs = make_vehicle(other, plate='SAM111')
    client.force_login(customer)

    client.post(reverse('vehicles:edit', kwargs={'pk': theirs.pk}), {**VEHICLE_DATA, 'make': 'Hacked'})
    client.post(reverse('vehicles:delete', kwargs={'pk': theirs.pk}))

    theirs.refresh_from_db()
    assert theirs.make == 'Toyota'


def test_admin_sees_every_vehicle(client, admin_user, customer, vehicle, make_user, make_vehicle):
    other = make_user('sam')
    theirs = make_vehicle(other, plate='SAM111')
    client.force_login(admin_user)

    response = client.get(reverse('vehicles:list'))

    assert set(response.context['vehicles']) == {vehicle, theirs}
    assert 'Owner' in response.content.decode()


# ---------------------------------------------------------------- create / edit / delete


def test_add_vehicle_page_loads(client, customer):
    client.force_login(customer)
    response = client.get(reverse('vehicles:create'))
    assert response.status_code == 200
    assert 'owner' not in response.context['form'].fields  # customers always own what they add


def test_customer_adds_a_vehicle_and_owns_it(client, customer):
    client.force_login(customer)

    response = client.post(reverse('vehicles:create'), {
        **VEHICLE_DATA, 'wof_expiry': '2030-06-01', 'rego_expiry': '2030-07-01',
    })

    vehicle = Vehicle.objects.get()
    assert response.status_code == 302
    assert response.url == reverse('vehicles:detail', kwargs={'pk': vehicle.pk})
    assert vehicle.owner == customer
    assert vehicle.plate == 'ABC123'
    assert vehicle.wof_expiry == datetime.date(2030, 6, 1)


def test_customer_cannot_set_owner(client, customer, make_user):
    other = make_user('sam')
    client.force_login(customer)

    client.post(reverse('vehicles:create'), {**VEHICLE_DATA, 'owner': other.pk})

    assert Vehicle.objects.get().owner == customer


def test_duplicate_plate_is_rejected_ignoring_case_and_spaces(client, customer, make_user, make_vehicle):
    make_vehicle(make_user('sam'), plate='ABC123')
    client.force_login(customer)

    response = client.post(reverse('vehicles:create'), VEHICLE_DATA)  # 'abc 123'

    assert response.status_code == 200
    assert 'already registered' in response.context['form'].errors['plate'][0]
    assert Vehicle.objects.count() == 1


@pytest.mark.parametrize('overrides, bad_field', [
    ({'plate': ''}, 'plate'),
    ({'plate': 'AB-123!'}, 'plate'),
    ({'plate': 'ABCDEFGHI'}, 'plate'),
    ({'make': ''}, 'make'),
    ({'year': '1850'}, 'year'),
    ({'year': 'abc'}, 'year'),
    ({'wof_expiry': 'not-a-date'}, 'wof_expiry'),
    ({'rego_expiry': '2999-01-01'}, 'rego_expiry'),
])
def test_vehicle_validation_errors(client, customer, overrides, bad_field):
    client.force_login(customer)

    response = client.post(reverse('vehicles:create'), {**VEHICLE_DATA, **overrides})

    assert response.status_code == 200
    assert bad_field in response.context['form'].errors
    assert not Vehicle.objects.exists()


def test_expiry_dates_are_optional(client, customer):
    client.force_login(customer)
    response = client.post(reverse('vehicles:create'), VEHICLE_DATA)
    assert response.status_code == 302
    assert Vehicle.objects.get().wof_expiry is None


def test_customer_can_edit_their_vehicle(client, customer, vehicle):
    client.force_login(customer)

    response = client.post(reverse('vehicles:edit', kwargs={'pk': vehicle.pk}), {
        **VEHICLE_DATA, 'plate': vehicle.plate, 'make': 'Honda', 'model': 'Civic',
    })

    assert response.status_code == 302
    vehicle.refresh_from_db()
    assert (vehicle.make, vehicle.model) == ('Honda', 'Civic')
    assert vehicle.owner == customer


def test_editing_keeps_the_same_plate_without_a_duplicate_error(client, customer, vehicle):
    client.force_login(customer)
    response = client.post(reverse('vehicles:edit', kwargs={'pk': vehicle.pk}), {**VEHICLE_DATA, 'plate': 'ABC123'})
    assert response.status_code == 302


def test_admin_adds_a_vehicle_for_a_customer(client, admin_user, customer):
    client.force_login(admin_user)

    form = client.get(reverse('vehicles:create')).context['form']
    assert set(form.fields['owner'].queryset) == {customer}

    response = client.post(reverse('vehicles:create'), {**VEHICLE_DATA, 'owner': customer.pk})

    assert response.status_code == 302
    assert Vehicle.objects.get().owner == customer


def test_admin_must_pick_an_owner(client, admin_user):
    client.force_login(admin_user)
    response = client.post(reverse('vehicles:create'), VEHICLE_DATA)
    assert response.status_code == 200
    assert 'owner' in response.context['form'].errors


def test_customer_deletes_a_vehicle_without_bookings(client, customer, vehicle):
    client.force_login(customer)
    url = reverse('vehicles:delete', kwargs={'pk': vehicle.pk})

    assert client.get(url).status_code == 200
    response = client.post(url)

    assert response.status_code == 302
    assert response.url == reverse('vehicles:list')
    assert not Vehicle.objects.exists()


def test_vehicle_with_bookings_cannot_be_deleted(client, customer, vehicle, make_booking):
    make_booking(customer, vehicle)
    client.force_login(customer)

    response = client.post(reverse('vehicles:delete', kwargs={'pk': vehicle.pk}), follow=True)

    assert Vehicle.objects.filter(pk=vehicle.pk).exists()
    assert Booking.objects.count() == 1
    assert 'cannot be deleted' in response.content.decode()


# ---------------------------------------------------------------- detail page


def test_detail_page_shows_service_history_newest_first(client, customer, vehicle, make_booking, open_day):
    older = make_booking(customer, vehicle, date=open_day, status='COMPLETED', service_type='Oil Change')
    newer = make_booking(customer, vehicle, date=open_day + datetime.timedelta(days=7), service_type='Brake Repair')
    client.force_login(customer)

    response = client.get(reverse('vehicles:detail', kwargs={'pk': vehicle.pk}))

    assert list(response.context['history']) == [newer, older]
    body = response.content.decode()
    assert 'Service history' in body and 'Brake Repair' in body
    assert body.index('Brake Repair') < body.index('Oil Change')
    assert f"{reverse('create_booking')}?vehicle={vehicle.pk}" in body


def test_detail_page_with_no_bookings(client, customer, vehicle):
    client.force_login(customer)
    body = client.get(reverse('vehicles:detail', kwargs={'pk': vehicle.pk})).content.decode()
    assert 'No bookings for this vehicle yet' in body


def test_expiry_badges_are_shown(client, customer, make_vehicle):
    today = timezone.localdate()
    car = make_vehicle(
        customer, wof_expiry=today - datetime.timedelta(days=2), rego_expiry=today + datetime.timedelta(days=10),
    )
    client.force_login(customer)

    body = client.get(reverse('vehicles:detail', kwargs={'pk': car.pk})).content.decode()

    assert 'Expired' in body
    assert 'Due soon' in body



# ---------------------------------------------------------------- mechanics: look up any vehicle by plate


def test_mechanic_sees_a_search_prompt_not_every_vehicle(client, mechanic, vehicle):
    client.force_login(mechanic)

    response = client.get(reverse('vehicles:list'))

    assert response.status_code == 200
    assert list(response.context['vehicles']) == []
    assert 'Enter at least two characters' in response.content.decode()
    assert '>ABC123<' not in response.content.decode()  # the vehicle is not listed (only the placeholder text mentions a plate)


def test_mechanic_search_needs_two_characters(client, mechanic, vehicle):
    client.force_login(mechanic)
    assert list(client.get(reverse('vehicles:list') + '?q=A').context['vehicles']) == []


@pytest.mark.parametrize('query', ['ABC123', 'abc123', 'abc 123', 'ABC', 'c12'])
def test_mechanic_finds_any_customers_vehicle_by_plate(client, mechanic, vehicle, query):
    client.force_login(mechanic)

    response = client.get(reverse('vehicles:list'), {'q': query})

    assert list(response.context['vehicles']) == [vehicle]
    assert vehicle.plate in response.content.decode()


def test_mechanic_search_with_no_match_says_so(client, mechanic, vehicle):
    client.force_login(mechanic)
    body = client.get(reverse('vehicles:list') + '?q=ZZZ999').content.decode()
    assert 'No vehicle in GarageLog matches' in body


def test_mechanic_list_has_no_add_button(client, mechanic, vehicle):
    client.force_login(mechanic)
    assert reverse('vehicles:create') not in client.get(reverse('vehicles:list') + '?q=ABC').content.decode()


def test_mechanic_can_read_a_vehicle_and_its_history_but_not_change_it(
        client, mechanic, vehicle, customer, make_booking):
    make_booking(customer, vehicle, status='COMPLETED', service_type='Oil Change')
    client.force_login(mechanic)

    response = client.get(reverse('vehicles:detail', kwargs={'pk': vehicle.pk}))

    body = response.content.decode()
    assert response.status_code == 200
    assert 'Service history' in body and 'Oil Change' in body
    assert reverse('vehicles:edit', kwargs={'pk': vehicle.pk}) not in body
    assert reverse('vehicles:delete', kwargs={'pk': vehicle.pk}) not in body
    assert f"{reverse('create_booking')}?vehicle={vehicle.pk}" in body  # but can book it for the owner


def test_history_shows_every_workshop_but_links_only_to_the_mechanics_own(
        client, mechanic, vehicle, customer, other_workshop, make_booking, open_day):
    here = make_booking(customer, vehicle, service_type='Brake Repair')
    there = make_booking(
        customer, vehicle, workshop=other_workshop, service_type='Oil Change',
        date=open_day + datetime.timedelta(days=7),
    )
    client.force_login(mechanic)

    response = client.get(reverse('vehicles:detail', kwargs={'pk': vehicle.pk}))

    body = response.content.decode()
    assert 'Brake Repair' in body and 'Oil Change' in body
    assert 'North Workshop' in body and 'Central Workshop' in body
    assert reverse('booking_detail', kwargs={'pk': here.pk}) in body
    assert reverse('booking_detail', kwargs={'pk': there.pk}) not in body  # a 404 for this mechanic


def test_owner_contact_details_are_hidden_until_they_have_booked_at_the_mechanics_workshop(
        client, mechanic, vehicle, customer, other_workshop, make_booking):
    customer.phone = '021 555 0199'
    customer.save()
    client.force_login(mechanic)
    url = reverse('vehicles:detail', kwargs={'pk': vehicle.pk})

    never_booked = client.get(url).content.decode()
    assert '021 555 0199' not in never_booked and customer.email not in never_booked
    assert 'Contact details are shown once' in never_booked

    make_booking(customer, vehicle, workshop=other_workshop)  # booked, but at a different workshop
    assert '021 555 0199' not in client.get(url).content.decode()

    make_booking(customer, vehicle, time=datetime.time(11, 0))  # now booked at this mechanic's workshop
    body = client.get(url).content.decode()
    assert '021 555 0199' in body and customer.email in body


def test_admin_can_search_all_vehicles_by_plate(client, admin_user, vehicle, make_user, make_vehicle):
    other = make_vehicle(make_user('sam'), plate='XYZ789')
    client.force_login(admin_user)

    everything = client.get(reverse('vehicles:list'))
    filtered = client.get(reverse('vehicles:list') + '?q=xyz')

    assert set(everything.context['vehicles']) == {vehicle, other}
    assert list(filtered.context['vehicles']) == [other]
