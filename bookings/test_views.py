import datetime

import pytest
from django.urls import reverse

from accounts.models import User

from . import scheduling
from .models import Booking
from .tests import frozen_now

pytestmark = pytest.mark.django_db


def names(response):
    return [template.name for template in response.templates]


# ---------------------------------------------------------------- access


@pytest.mark.parametrize('url_name, needs_pk', [
    ('booking_list', False), ('create_booking', False), ('booking_detail', True),
    ('booking_edit', True), ('booking_cancel', True), ('booking_delete', True),
])
def test_anonymous_users_are_sent_to_login(client, customer, vehicle, make_booking, url_name, needs_pk):
    kwargs = {'pk': make_booking(customer, vehicle).pk} if needs_pk else {}
    url = reverse(url_name, kwargs=kwargs)

    response = client.get(url)

    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={url}"


def test_mechanics_cannot_delete_bookings(client, mechanic, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle, mechanic=mechanic)
    client.force_login(mechanic)

    response = client.post(reverse('booking_delete', kwargs={'pk': booking.pk}))

    assert response.status_code == 403
    assert Booking.objects.filter(pk=booking.pk).exists()


def test_customers_cannot_delete_bookings(client, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle)
    client.force_login(customer)

    response = client.post(reverse('booking_delete', kwargs={'pk': booking.pk}))

    assert response.status_code == 403
    assert Booking.objects.filter(pk=booking.pk).exists()


# ---------------------------------------------------------------- who sees what


def test_customer_only_sees_their_own_bookings(client, customer, vehicle, make_user, make_vehicle, make_booking):
    other = make_user('sam')
    theirs = make_booking(other, make_vehicle(other, plate='SAM111'), service_type='Brake Repair')
    mine = make_booking(customer, vehicle, service_type='Oil Change')
    client.force_login(customer)

    response = client.get(reverse('booking_list'))

    assert list(response.context['bookings']) == [mine]
    assert 'Brake Repair' not in response.content.decode()
    assert response.context['page_title'] == 'My bookings'
    assert client.get(reverse('booking_detail', kwargs={'pk': theirs.pk})).status_code == 404


def test_customer_cannot_touch_someone_elses_booking(client, customer, make_user, make_vehicle, make_booking):
    other = make_user('sam')
    theirs = make_booking(other, make_vehicle(other, plate='SAM111'))
    client.force_login(customer)

    assert client.get(reverse('booking_edit', kwargs={'pk': theirs.pk})).status_code == 404
    assert client.get(reverse('booking_cancel', kwargs={'pk': theirs.pk})).status_code == 404
    assert client.post(reverse('booking_cancel', kwargs={'pk': theirs.pk})).status_code == 404
    theirs.refresh_from_db()
    assert theirs.status == 'PENDING'


def test_mechanic_sees_every_booking_at_their_workshop_but_no_others(
        client, mechanic, make_user, other_workshop, customer, vehicle, make_vehicle, make_booking):
    assigned = make_booking(customer, vehicle, mechanic=mechanic)
    unassigned = make_booking(customer, vehicle, time=datetime.time(11, 0))
    other_vehicle = make_vehicle(customer, plate='NORTH01')
    elsewhere = make_booking(customer, other_vehicle, workshop=other_workshop)
    client.force_login(mechanic)

    response = client.get(reverse('booking_list'))

    assert set(response.context['bookings']) == {assigned, unassigned}
    assert response.context['page_title'] == 'Bookings at Central Workshop'
    assert client.get(reverse('booking_detail', kwargs={'pk': assigned.pk})).status_code == 200
    assert client.get(reverse('booking_detail', kwargs={'pk': unassigned.pk})).status_code == 200
    assert client.get(reverse('booking_detail', kwargs={'pk': elsewhere.pk})).status_code == 404


def test_admin_sees_all_bookings_and_can_filter_by_status(client, admin_user, customer, vehicle, make_booking):
    pending = make_booking(customer, vehicle)
    confirmed = make_booking(customer, vehicle, time=datetime.time(11, 0), status='CONFIRMED')
    client.force_login(admin_user)

    everything = client.get(reverse('booking_list'))
    only_confirmed = client.get(reverse('booking_list') + '?status=CONFIRMED')
    nonsense = client.get(reverse('booking_list') + '?status=NOPE')

    assert set(everything.context['bookings']) == {pending, confirmed}
    assert list(only_confirmed.context['bookings']) == [confirmed]
    assert set(nonsense.context['bookings']) == {pending, confirmed}  # unknown filter is ignored
    assert everything.context['page_title'] == 'All bookings'


def test_booking_list_can_be_sorted_and_switches_to_month_calendar(
    client, admin_user, customer, vehicle, make_booking
):
    first_date = datetime.date(2026, 11, 5)
    later_date = datetime.date(2026, 11, 12)
    first = make_booking(customer, vehicle, date=first_date, service_type='Oil Change')
    later = make_booking(
        customer,
        vehicle,
        date=later_date,
        time=datetime.time(11, 0),
        service_type='Brake Repair',
    )
    outside_month = make_booking(
        customer,
        vehicle,
        date=datetime.date(2026, 12, 3),
        service_type='Tyre Change',
    )
    client.force_login(admin_user)

    ascending = client.get(reverse('booking_list') + '?sort=date_asc')
    descending = client.get(reverse('booking_list') + '?sort=date_desc')
    calendar_view = client.get(
        reverse('booking_list') + '?view=calendar&month=2026-11'
    )

    assert list(ascending.context['bookings']) == [first, later, outside_month]
    assert list(descending.context['bookings']) == [outside_month, later, first]
    assert calendar_view.context['view_mode'] == 'calendar'
    assert list(calendar_view.context['bookings']) == [first, later]
    assert calendar_view.context['month_label'] == 'November 2026'
    assert any(
        booking == first
        for week in calendar_view.context['calendar_weeks']
        for day in week
        for booking in day['bookings']
    )
    assert b'Calendar' in calendar_view.content
    assert b'Brake Repair' in calendar_view.content
    assert b'Tyre Change' not in calendar_view.content


# ---------------------------------------------------------------- customer creates a booking


def test_customer_without_a_vehicle_is_sent_to_add_one(client, customer, workshop):
    client.force_login(customer)

    response = client.get(reverse('create_booking'))

    assert response.status_code == 302
    assert response.url == reverse('vehicles:create')


def test_create_booking_page_loads_and_preselects_vehicle(client, customer, vehicle, workshop):
    client.force_login(customer)

    response = client.get(reverse('create_booking') + f'?vehicle={vehicle.pk}')

    assert response.status_code == 200
    assert response.context['form']['vehicle'].value() == str(vehicle.pk)
    assert 'bookings/create_booking.html' in names(response)


def test_customer_creates_pending_booking_for_themselves(client, customer, vehicle, booking_data):
    client.force_login(customer)

    response = client.post(reverse('create_booking'), booking_data(vehicle, notes='Squeaky brakes'))

    booking = Booking.objects.get()
    assert response.status_code == 302
    assert response.url == reverse('booking_detail', kwargs={'pk': booking.pk})
    assert booking.customer == customer
    assert booking.vehicle == vehicle
    assert booking.status == 'PENDING'
    assert booking.mechanic is None
    assert booking.booking_time == datetime.time(10, 0)


def test_customer_cannot_set_status_mechanic_or_customer(client, customer, vehicle, mechanic, make_user, booking_data):
    other = make_user('sam')
    client.force_login(customer)

    client.post(reverse('create_booking'), booking_data(
        vehicle, status='CONFIRMED', mechanic=mechanic.pk, customer=other.pk,
    ))

    booking = Booking.objects.get()
    assert booking.status == 'PENDING'
    assert booking.mechanic is None
    assert booking.customer == customer


def test_customer_cannot_book_someone_elses_vehicle(client, customer, vehicle, make_user, make_vehicle, booking_data):
    other = make_user('sam')
    theirs = make_vehicle(other, plate='SAM111')
    client.force_login(customer)

    response = client.post(reverse('create_booking'), booking_data(theirs))

    assert response.status_code == 200
    assert 'vehicle' in response.context['form'].errors
    assert not Booking.objects.exists()


def test_other_service_is_saved_as_the_service(client, customer, vehicle, booking_data):
    client.force_login(customer)

    client.post(reverse('create_booking'), booking_data(vehicle, service_type='Other', other_service='Air con regas'))

    assert Booking.objects.get().service_type == 'Air con regas'


def test_invalid_booking_shows_errors_and_saves_nothing(client, customer, vehicle, booking_data):
    client.force_login(customer)

    response = client.post(reverse('create_booking'), booking_data(vehicle, booking_time='', service_type=''))

    assert response.status_code == 200
    assert {'booking_time', 'service_type'} <= set(response.context['form'].errors)
    assert 'id="form-errors"' in response.content.decode()
    assert not Booking.objects.exists()


# ---------------------------------------------------------------- edit


def test_customer_can_edit_their_upcoming_booking(client, customer, vehicle, make_booking, booking_data):
    booking = make_booking(customer, vehicle)
    client.force_login(customer)

    page = client.get(reverse('booking_edit', kwargs={'pk': booking.pk}))
    assert page.status_code == 200
    assert page.context['form']['booking_time'].value() == '10:00'  # saved time is preselected

    response = client.post(
        reverse('booking_edit', kwargs={'pk': booking.pk}),
        booking_data(vehicle, booking_time='14:00', notes='Moved to the afternoon'),
    )

    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.booking_time == datetime.time(14, 0)
    assert booking.notes == 'Moved to the afternoon'
    assert booking.customer == customer


def test_editing_a_custom_service_shows_it_as_other(client, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle, service_type='Air con regas')
    client.force_login(customer)

    form = client.get(reverse('booking_edit', kwargs={'pk': booking.pk})).context['form']

    assert form['service_type'].value() == 'Other'
    assert form['other_service'].value() == 'Air con regas'


def test_customer_cannot_edit_a_booking_that_has_started(client, customer, vehicle, make_booking, open_day):
    booking = make_booking(customer, vehicle)
    client.force_login(customer)

    with frozen_now(open_day, 11):  # the 10:00 booking is already under way
        assert client.get(reverse('booking_edit', kwargs={'pk': booking.pk})).status_code == 403


def test_customer_cannot_edit_a_cancelled_booking(client, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle, status='CANCELLED')
    client.force_login(customer)

    assert client.get(reverse('booking_edit', kwargs={'pk': booking.pk})).status_code == 403


# ---------------------------------------------------------------- cancel and delete


def test_customer_cancels_booking_and_it_is_kept(client, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle)
    client.force_login(customer)
    url = reverse('booking_cancel', kwargs={'pk': booking.pk})

    assert client.get(url).status_code == 200  # confirmation page, nothing changed yet
    booking.refresh_from_db()
    assert booking.status == 'PENDING'

    response = client.post(url)

    assert response.status_code == 302
    assert response.url == reverse('booking_list')
    booking.refresh_from_db()
    assert booking.status == 'CANCELLED'


def test_cancelled_booking_cannot_be_cancelled_again(client, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle, status='CANCELLED')
    client.force_login(customer)

    assert client.post(reverse('booking_cancel', kwargs={'pk': booking.pk})).status_code == 403


def test_customer_cannot_cancel_after_the_booking_has_started(client, customer, vehicle, make_booking, open_day):
    booking = make_booking(customer, vehicle)
    client.force_login(customer)

    with frozen_now(open_day, 11):
        assert client.post(reverse('booking_cancel', kwargs={'pk': booking.pk})).status_code == 403
    booking.refresh_from_db()
    assert booking.status == 'PENDING'


def test_admin_can_delete_a_booking(client, admin_user, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle)
    client.force_login(admin_user)
    url = reverse('booking_delete', kwargs={'pk': booking.pk})

    assert client.get(url).status_code == 200
    response = client.post(url)

    assert response.status_code == 302
    assert not Booking.objects.exists()


# ---------------------------------------------------------------- admin


def test_admin_can_book_on_behalf_of_a_customer(client, admin_user, customer, vehicle, mechanic, booking_data):
    client.force_login(admin_user)

    response = client.post(reverse('create_booking'), booking_data(
        vehicle, customer=customer.pk, mechanic=mechanic.pk, status='CONFIRMED',
    ))

    assert response.status_code == 302
    booking = Booking.objects.get()
    assert (booking.customer, booking.vehicle, booking.mechanic, booking.status) == (
        customer, vehicle, mechanic, 'CONFIRMED')


def test_admin_cannot_pair_a_customer_with_another_customers_vehicle(
        client, admin_user, customer, vehicle, make_user, booking_data):
    other = make_user('sam')
    client.force_login(admin_user)

    response = client.post(reverse('create_booking'), booking_data(vehicle, customer=other.pk, status='PENDING'))

    assert response.status_code == 200
    assert 'different customer' in response.context['form'].errors['vehicle'][0]
    assert not Booking.objects.exists()


def test_admin_form_only_offers_customers_and_mechanics(client, admin_user, customer, mechanic):
    client.force_login(admin_user)

    form = client.get(reverse('create_booking')).context['form']

    assert set(form.fields['customer'].queryset) == {customer}
    assert set(form.fields['mechanic'].queryset) == {mechanic}


def test_admin_assigns_mechanic_and_confirms_booking(client, admin_user, customer, vehicle, mechanic, make_booking, booking_data):
    booking = make_booking(customer, vehicle)
    client.force_login(admin_user)

    response = client.post(
        reverse('booking_edit', kwargs={'pk': booking.pk}),
        booking_data(vehicle, customer=customer.pk, mechanic=mechanic.pk, status='CONFIRMED'),
    )

    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.mechanic == mechanic
    assert booking.status == 'CONFIRMED'


def test_admin_can_complete_a_booking_whose_date_has_passed(client, admin_user, customer, vehicle, mechanic, make_booking, booking_data, open_day):
    booking = make_booking(customer, vehicle, status='CONFIRMED', mechanic=mechanic)
    client.force_login(admin_user)

    with frozen_now(open_day + datetime.timedelta(days=3), 9):  # the booking is now in the past
        response = client.post(
            reverse('booking_edit', kwargs={'pk': booking.pk}),
            booking_data(vehicle, customer=customer.pk, mechanic=mechanic.pk, status='COMPLETED'),
        )

    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.status == 'COMPLETED'


# ---------------------------------------------------------------- pages


def test_detail_page_shows_actions_only_when_allowed(client, customer, vehicle, make_booking):
    upcoming = make_booking(customer, vehicle)
    done = make_booking(customer, vehicle, time=datetime.time(11, 0), status='COMPLETED')
    client.force_login(customer)

    upcoming_page = client.get(reverse('booking_detail', kwargs={'pk': upcoming.pk})).content.decode()
    done_page = client.get(reverse('booking_detail', kwargs={'pk': done.pk})).content.decode()

    assert reverse('booking_edit', kwargs={'pk': upcoming.pk}) in upcoming_page
    assert reverse('booking_cancel', kwargs={'pk': upcoming.pk}) in upcoming_page
    assert reverse('booking_delete', kwargs={'pk': upcoming.pk}) not in upcoming_page  # admins only
    assert reverse('booking_edit', kwargs={'pk': done.pk}) not in done_page
    assert reverse('booking_cancel', kwargs={'pk': done.pk}) not in done_page


def test_navbar_links_depend_on_role(client, customer, mechanic, admin_user):
    def navbar_for(user):
        client.force_login(user)
        return client.get(reverse('dashboard'), follow=True).content.decode()

    for user in (customer, mechanic, admin_user):
        page = navbar_for(user)
        assert reverse('vehicles:list') in page and reverse('booking_list') in page


# ---------------------------------------------------------------- admin: vehicle follows the selected customer


def test_admin_vehicle_options_are_tagged_with_their_owner(
        client, admin_user, customer, vehicle, make_user, make_vehicle):
    other = make_user('sam')
    theirs = make_vehicle(other, plate='SAM111')
    client.force_login(admin_user)

    body = client.get(reverse('create_booking')).content.decode()

    # The page's script uses data-owner to list only the selected customer's vehicles.
    assert f'<option value="{vehicle.pk}" data-owner="{customer.pk}">' in body
    assert f'<option value="{theirs.pk}" data-owner="{other.pk}">' in body


def test_customer_form_has_no_owner_tags_or_customer_field(client, customer, vehicle, workshop):
    client.force_login(customer)

    response = client.get(reverse('create_booking'))

    assert 'customer' not in response.context['form'].fields
    assert ' data-owner="' not in response.content.decode()  # no option carries an owner tag


def test_admin_booking_from_a_vehicle_page_preselects_its_owner(client, admin_user, customer, vehicle):
    client.force_login(admin_user)

    form = client.get(reverse('create_booking') + f'?vehicle={vehicle.pk}').context['form']

    assert str(form['customer'].value()) == str(customer.pk)
    assert str(form['vehicle'].value()) == str(vehicle.pk)


def test_admin_cannot_book_a_vehicle_that_is_not_the_selected_customers(
        client, admin_user, customer, vehicle, make_user, make_vehicle, booking_data):
    other = make_user('sam')
    theirs = make_vehicle(other, plate='SAM111')
    client.force_login(admin_user)

    # Customer is casey, but the vehicle belongs to sam (for example, if the page's script is off).
    response = client.post(reverse('create_booking'), booking_data(theirs, customer=customer.pk, status='PENDING'))

    assert response.status_code == 200
    assert 'belongs to a different customer' in response.context['form'].errors['vehicle'][0]
    assert not Booking.objects.exists()


def test_admin_edit_form_starts_with_the_bookings_customer_selected(client, admin_user, customer, vehicle, make_booking):
    booking = make_booking(customer, vehicle)
    client.force_login(admin_user)

    form = client.get(reverse('booking_edit', kwargs={'pk': booking.pk})).context['form']

    assert form['customer'].value() == customer.pk
    assert form['vehicle'].value() == vehicle.pk


# ---------------------------------------------------------------- workshops: customers


def test_customer_with_no_workshops_available_is_told_so(client, customer, vehicle):
    client.force_login(customer)

    response = client.get(reverse('create_booking'))

    assert response.status_code == 302
    assert response.url == reverse('dashboard')


def test_customer_picks_the_workshop_when_there_are_several(client, customer, vehicle, workshop, other_workshop, booking_data):
    client.force_login(customer)

    page = client.get(reverse('create_booking'))
    assert {w.name for w in page.context['form'].fields['workshop'].queryset} == {workshop.name, other_workshop.name}
    assert page.context['form']['workshop'].value() is None  # nothing preselected when there is a choice

    response = client.post(reverse('create_booking'), booking_data(vehicle, workshop=other_workshop.pk))

    assert response.status_code == 302
    assert Booking.objects.get().workshop == other_workshop


def test_customer_cannot_book_at_an_inactive_workshop(client, customer, vehicle, make_workshop, booking_data):
    closed = make_workshop('Closed', is_active=False)
    client.force_login(customer)

    response = client.post(reverse('create_booking'), booking_data(vehicle, workshop=closed.pk))

    assert response.status_code == 200
    assert 'workshop' in response.context['form'].errors


def test_customer_cannot_move_a_booking_to_another_workshop(
        client, customer, vehicle, workshop, other_workshop, make_booking, booking_data):
    booking = make_booking(customer, vehicle)
    client.force_login(customer)

    client.post(
        reverse('booking_edit', kwargs={'pk': booking.pk}),
        booking_data(vehicle, workshop=other_workshop.pk, notes='Trying to move it'),
    )

    booking.refresh_from_db()
    assert booking.workshop == workshop
    assert booking.notes == 'Trying to move it'


def test_detail_page_shows_the_workshop(client, customer, vehicle, make_workshop, make_booking):
    shop = make_workshop('Takapuna Motors', address='5 Lake Road', phone='09 555 1234')
    booking = make_booking(customer, vehicle, workshop=shop)
    client.force_login(customer)

    body = client.get(reverse('booking_detail', kwargs={'pk': booking.pk})).content.decode()

    assert 'Takapuna Motors' in body and '5 Lake Road' in body and '09 555 1234' in body


# ---------------------------------------------------------------- workshops: mechanics


def test_mechanic_creates_a_booking_for_a_customer_at_their_own_workshop(
        client, mechanic, customer, vehicle, workshop, booking_data):
    client.force_login(mechanic)

    form = client.get(reverse('create_booking')).context['form']
    assert 'workshop' not in form.fields  # a mechanic's bookings are always at their own workshop

    response = client.post(reverse('create_booking'), booking_data(
        vehicle, customer=customer.pk, mechanic=mechanic.pk, status='CONFIRMED',
    ))

    assert response.status_code == 302
    booking = Booking.objects.get()
    assert (booking.customer, booking.workshop, booking.mechanic, booking.status) == (
        customer, workshop, mechanic, 'CONFIRMED')


def test_mechanic_cannot_place_a_booking_at_another_workshop(
        client, mechanic, customer, vehicle, workshop, other_workshop, booking_data):
    client.force_login(mechanic)

    client.post(reverse('create_booking'), booking_data(
        vehicle, customer=customer.pk, workshop=other_workshop.pk, status='PENDING',
    ))

    assert Booking.objects.get().workshop == workshop  # the submitted workshop is ignored


def test_mechanic_can_only_assign_mechanics_from_their_workshop(
        client, mechanic, make_user, other_workshop, customer, vehicle):
    colleague = make_user('colleague', User.Role.MECHANIC)
    northern = make_user('northern', User.Role.MECHANIC, workshop=other_workshop)
    client.force_login(mechanic)

    form = client.get(reverse('create_booking')).context['form']

    assert set(form.fields['mechanic'].queryset) == {mechanic, colleague}
    assert northern not in form.fields['mechanic'].queryset


def test_mechanic_time_choices_follow_their_workshops_hours(client, mechanic, workshop, customer, vehicle):
    client.force_login(mechanic)

    form = client.get(reverse('create_booking')).context['form']

    assert [label for _, label in form.fields['booking_time'].choices][1:] == [
        label for _, label in scheduling.slot_choices(workshop)]


def test_mechanic_can_edit_and_cancel_bookings_at_their_workshop(client, mechanic, customer, vehicle, make_booking, booking_data):
    booking = make_booking(customer, vehicle)  # unassigned, but at the mechanic's workshop
    client.force_login(mechanic)

    edit = client.post(
        reverse('booking_edit', kwargs={'pk': booking.pk}),
        booking_data(vehicle, customer=customer.pk, mechanic=mechanic.pk, status='CONFIRMED', notes='Taking this one'),
    )
    assert edit.status_code == 302
    booking.refresh_from_db()
    assert (booking.mechanic, booking.status, booking.notes) == (mechanic, 'CONFIRMED', 'Taking this one')

    cancel = client.post(reverse('booking_cancel', kwargs={'pk': booking.pk}))
    assert cancel.status_code == 302
    booking.refresh_from_db()
    assert booking.status == 'CANCELLED'


def test_mechanic_cannot_touch_another_workshops_booking(
        client, mechanic, customer, vehicle, other_workshop, make_booking):
    elsewhere = make_booking(customer, vehicle, workshop=other_workshop)
    client.force_login(mechanic)

    for url_name in ('booking_detail', 'booking_edit', 'booking_cancel'):
        assert client.get(reverse(url_name, kwargs={'pk': elsewhere.pk})).status_code == 404
    assert client.post(reverse('booking_cancel', kwargs={'pk': elsewhere.pk})).status_code == 404
    elsewhere.refresh_from_db()
    assert elsewhere.status == 'PENDING'


def test_mechanic_status_filter_applies_within_their_workshop(client, mechanic, customer, vehicle, make_booking):
    pending = make_booking(customer, vehicle)
    confirmed = make_booking(customer, vehicle, time=datetime.time(11, 0), status='CONFIRMED')
    client.force_login(mechanic)

    response = client.get(reverse('booking_list') + '?status=CONFIRMED')

    assert list(response.context['bookings']) == [confirmed]
    assert pending not in response.context['bookings']


def test_mechanic_without_a_workshop_cannot_make_bookings_and_sees_none(client, make_user, customer, vehicle, make_booking):
    drifter = make_user('drifter', User.Role.MECHANIC)
    drifter.workshop = None
    drifter.save()
    make_booking(customer, vehicle)
    client.force_login(drifter)

    assert list(client.get(reverse('booking_list')).context['bookings']) == []
    response = client.get(reverse('create_booking'))
    assert response.status_code == 302
    assert response.url == reverse('dashboard')


# ---------------------------------------------------------------- admin: workshop and mechanic follow each other


def test_admin_chooses_the_workshop_and_mechanics_are_tagged_with_theirs(
        client, admin_user, mechanic, make_user, other_workshop, workshop, customer, vehicle):
    northern = make_user('northern', User.Role.MECHANIC, workshop=other_workshop)
    client.force_login(admin_user)

    response = client.get(reverse('create_booking'))
    body = response.content.decode()

    assert 'workshop' in response.context['form'].fields
    assert f'<option value="{mechanic.pk}" data-workshop="{workshop.pk}">' in body
    assert f'<option value="{northern.pk}" data-workshop="{other_workshop.pk}">' in body


def test_admin_can_book_at_any_workshop(client, admin_user, customer, vehicle, other_workshop, booking_data):
    client.force_login(admin_user)

    response = client.post(reverse('create_booking'), booking_data(
        vehicle, customer=customer.pk, workshop=other_workshop.pk, status='PENDING',
    ))

    assert response.status_code == 302
    assert Booking.objects.get().workshop == other_workshop


def test_admin_dashboard_link_to_workshops_uses_the_admin_site(client, admin_user, workshop):
    client.force_login(admin_user)
    body = client.get(reverse('admin_dashboard')).content.decode()
    assert reverse('admin:workshops_workshop_changelist') in body


# ---------------------------------------------------------------- the parts warehouse takes no bookings


def test_customers_are_not_offered_the_warehouse(client, customer, vehicle, workshop, warehouse):
    client.force_login(customer)

    form = client.get(reverse('create_booking')).context['form']

    assert set(form.fields['workshop'].queryset) == {workshop}
    assert str(form['workshop'].value()) == str(workshop.pk)  # the only bookable workshop is preselected


def test_a_customer_cannot_book_at_the_warehouse_by_posting_its_id(client, customer, vehicle, warehouse, booking_data):
    client.force_login(customer)

    response = client.post(reverse('create_booking'), booking_data(vehicle, workshop=warehouse.pk))

    assert response.status_code == 200
    assert 'workshop' in response.context['form'].errors
    assert not Booking.objects.exists()


def test_when_only_the_warehouse_exists_customers_are_told_no_workshops_are_taking_bookings(
        client, customer, vehicle, warehouse):
    client.force_login(customer)

    response = client.get(reverse('create_booking'), follow=True)

    assert response.redirect_chain[0][0] == reverse('dashboard')  # then on to the role's own dashboard
    assert 'No workshops are taking bookings' in response.content.decode()


def test_admins_are_not_offered_the_warehouse_either(client, admin_user, customer, vehicle, workshop, warehouse, booking_data):
    client.force_login(admin_user)

    form = client.get(reverse('create_booking')).context['form']
    assert set(form.fields['workshop'].queryset) == {workshop}

    response = client.post(reverse('create_booking'), booking_data(
        vehicle, customer=customer.pk, workshop=warehouse.pk, status='PENDING',
    ))
    assert response.status_code == 200 and not Booking.objects.exists()


def test_warehouse_staff_cannot_make_bookings(client, warehouse_staff, customer, vehicle):
    client.force_login(warehouse_staff)

    response = client.get(reverse('create_booking'), follow=True)

    assert response.redirect_chain[0][0] == reverse('dashboard')  # then on to the role's own dashboard
    assert "parts warehouse and doesn't take bookings" in response.content.decode().replace('&#x27;', "'")


def test_warehouse_staff_navigation_hides_vehicles_and_bookings_but_keeps_stock_tools(
    client, warehouse_staff
):
    client.force_login(warehouse_staff)

    body = client.get(reverse('booking_list')).content.decode()

    assert f'href="{reverse("vehicles:list")}"' not in body
    assert f'href="{reverse("booking_list")}"' not in body
    assert f'href="{reverse("inventory:search")}"' in body
    assert 'Warehouse orders' in body


def test_workshop_mechanic_navigation_keeps_vehicles_and_bookings(client, mechanic):
    client.force_login(mechanic)

    body = client.get(reverse('booking_list')).content.decode()

    assert f'href="{reverse("vehicles:list")}"' in body
    assert f'href="{reverse("booking_list")}"' in body


def test_an_old_booking_at_a_workshop_that_became_the_warehouse_can_still_be_closed_off(
        client, admin_user, customer, vehicle, warehouse, make_booking, booking_data):
    old = make_booking(customer, vehicle, workshop=warehouse, status='CONFIRMED')
    client.force_login(admin_user)

    keep_active = client.post(
        reverse('booking_edit', kwargs={'pk': old.pk}),
        booking_data(vehicle, customer=customer.pk, workshop=warehouse.pk, status='CONFIRMED'),
    )
    assert keep_active.status_code == 200
    assert "parts warehouse and doesn't take bookings" in keep_active.content.decode().replace('&#x27;', "'")

    cancel = client.post(
        reverse('booking_edit', kwargs={'pk': old.pk}),
        booking_data(vehicle, customer=customer.pk, workshop=warehouse.pk, status='CANCELLED'),
    )
    assert cancel.status_code == 302
    old.refresh_from_db()
    assert old.status == 'CANCELLED'


def test_an_admin_can_move_an_old_warehouse_booking_to_a_real_workshop(
        client, admin_user, customer, vehicle, workshop, warehouse, make_booking, booking_data):
    old = make_booking(customer, vehicle, workshop=warehouse, status='CONFIRMED')
    client.force_login(admin_user)

    response = client.post(
        reverse('booking_edit', kwargs={'pk': old.pk}),
        booking_data(vehicle, customer=customer.pk, workshop=workshop.pk, status='CONFIRMED'),
    )

    assert response.status_code == 302
    old.refresh_from_db()
    assert old.workshop == workshop
