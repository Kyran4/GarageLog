import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from bookings.tests import frozen_now
from jobs.models import JobCard, JobPart

pytestmark = pytest.mark.django_db

DASHBOARDS = {
    'customer_dashboard': User.Role.CUSTOMER,
    'mechanic_dashboard': User.Role.MECHANIC,
    'admin_dashboard': User.Role.ADMIN,
}
ROLES = [User.Role.CUSTOMER, User.Role.MECHANIC, User.Role.ADMIN]


def template_names(response):
    return [t.name for t in response.templates]


def test_home_page_loads(client, db):
    response = client.get(reverse('home'))
    assert response.status_code == 200
    assert b'Log in' in response.content


def test_home_page_links_to_dashboard_when_logged_in(client, customer):
    client.force_login(customer)
    assert reverse('dashboard').encode() in client.get(reverse('home')).content


def test_dashboard_redirect_requires_login(client, db):
    response = client.get(reverse('dashboard'))
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={reverse('dashboard')}"


@pytest.mark.parametrize('role, expected', [
    (User.Role.CUSTOMER, 'customer_dashboard'),
    (User.Role.MECHANIC, 'mechanic_dashboard'),
    (User.Role.ADMIN, 'admin_dashboard'),
])
def test_dashboard_redirects_to_role_dashboard(client, make_user, role, expected):
    client.force_login(make_user('someone', role))
    response = client.get(reverse('dashboard'))
    assert response.status_code == 302
    assert response.url == reverse(expected)


def test_django_superuser_lands_on_admin_dashboard(client, make_user):
    client.force_login(make_user('root', User.Role.CUSTOMER, is_superuser=True, is_staff=True))
    assert client.get(reverse('dashboard')).url == reverse('admin_dashboard')


@pytest.mark.parametrize('url_name', DASHBOARDS)
def test_anonymous_users_are_sent_to_login(client, db, url_name):
    response = client.get(reverse(url_name))
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={reverse(url_name)}"


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('url_name, allowed_role', DASHBOARDS.items())
def test_each_dashboard_is_only_open_to_its_own_role(client, make_user, url_name, allowed_role, role):
    client.force_login(make_user('someone', role))

    response = client.get(reverse(url_name))

    if role == allowed_role:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert '403.html' in template_names(response)


def test_login_then_land_on_correct_dashboard(client, make_user, password):
    make_user('mech', User.Role.MECHANIC)
    response = client.post(reverse('accounts:login'), {'username': 'mech', 'password': password}, follow=True)
    assert response.redirect_chain[-1][0] == reverse('mechanic_dashboard')
    assert response.status_code == 200


def test_customer_dashboard_content(client, customer):
    client.force_login(customer)
    response = client.get(reverse('customer_dashboard'))
    assert 'Welcome, Casey' in response.content.decode()
    assert 'dashboard/customer.html' in template_names(response)


def test_admin_dashboard_lists_users_and_counts(client, admin_user, customer, mechanic):
    client.force_login(admin_user)
    response = client.get(reverse('admin_dashboard'))

    assert response.status_code == 200
    assert response.context['total_users'] == 3
    assert response.context['customer_count'] == 1
    assert response.context['mechanic_count'] == 1
    assert response.context['admin_count'] == 1
    assert list(response.context['customers']) == [customer]
    assert list(response.context['mechanics']) == [mechanic]
    assert list(response.context['admins']) == [admin_user]
    body = response.content.decode()
    assert 'customer@example.com' in body
    assert 'mechanic@example.com' in body


def test_admin_dashboard_paginates_each_role_list_independently(client, admin_user, make_user):
    for number in range(25):
        make_user(f'bulk{number}')
    client.force_login(admin_user)

    first = client.get(reverse('admin_dashboard'))
    second = client.get(reverse('admin_dashboard') + '?customers_page=2')

    assert len(first.context['customers']) == 20
    assert len(second.context['customers']) == 5
    assert len(second.context['admins']) == 1


def test_admin_dashboard_groups_superusers_as_admin(client, admin_user, make_user):
    root = make_user('root', User.Role.CUSTOMER, is_superuser=True, is_staff=True)
    client.force_login(admin_user)

    response = client.get(reverse('admin_dashboard'))

    assert root not in response.context['customers']
    assert root in response.context['admins']
    assert 'root@example.com' in response.content.decode()
    assert response.context['admin_count'] == 2


def test_navbar_changes_with_login_state(client, customer):
    anonymous = client.get(reverse('home')).content.decode()
    assert 'Sign up' in anonymous and 'Log out' not in anonymous

    client.force_login(customer)
    logged_in = client.get(reverse('home')).content.decode()
    assert 'Log out' in logged_in and 'Sign up' not in logged_in


def test_custom_404_page(client, db):
    response = client.get('/this-page-does-not-exist/')
    assert response.status_code == 404
    assert '404.html' in template_names(response)


def test_skip_link_and_main_landmark_present(client, db):
    body = client.get(reverse('home')).content.decode()
    assert 'href="#main-content"' in body
    assert 'id="main-content"' in body


# ---------------------------------------------------------------- live dashboard data


def test_customer_dashboard_counts_vehicles_and_upcoming_bookings(client, customer, vehicle, make_booking, open_day):
    make_booking(customer, vehicle)
    make_booking(customer, vehicle, time=datetime.time(11, 0), status='CANCELLED')  # not upcoming
    client.force_login(customer)

    response = client.get(reverse('customer_dashboard'))

    assert response.context['vehicle_count'] == 1
    assert response.context['upcoming_count'] == 1
    assert len(response.context['next_bookings']) == 1
    body = response.content.decode()
    assert reverse('vehicles:list') in body and reverse('booking_list') in body
    assert reverse('create_booking') in body


def test_customer_dashboard_ignores_bookings_that_already_happened(client, customer, vehicle, make_booking, open_day):
    make_booking(customer, vehicle)
    client.force_login(customer)

    with frozen_now(open_day, 13):  # the 10:00 booking has passed
        response = client.get(reverse('customer_dashboard'))

    assert response.context['upcoming_count'] == 0
    assert 'You have no upcoming bookings' in response.content.decode()


def test_customer_dashboard_only_counts_their_own_data(client, customer, vehicle, make_user, make_vehicle, make_booking):
    other = make_user('sam')
    make_booking(other, make_vehicle(other, plate='SAM111'))
    client.force_login(customer)

    response = client.get(reverse('customer_dashboard'))

    assert response.context['vehicle_count'] == 1
    assert response.context['upcoming_count'] == 0


def test_customer_dashboard_flags_expiring_wof_and_rego(client, customer, make_vehicle):
    today = timezone.localdate()
    make_vehicle(customer, plate='SOON1', wof_expiry=today + datetime.timedelta(days=5))
    make_vehicle(customer, plate='FINE1', wof_expiry=today + datetime.timedelta(days=200))
    client.force_login(customer)

    response = client.get(reverse('customer_dashboard'))

    assert [v.plate for v in response.context['expiring_vehicles']] == ['SOON1']


def test_mechanic_dashboard_shows_the_workshops_bookings_and_which_are_theirs(
        client, mechanic, make_user, other_workshop, customer, vehicle, make_vehicle, make_booking):
    colleague = make_user('colleague', User.Role.MECHANIC)
    make_booking(customer, vehicle, mechanic=mechanic)
    make_booking(customer, vehicle, mechanic=colleague, time=datetime.time(11, 0))
    make_booking(customer, make_vehicle(customer, plate='NORTH01'), workshop=other_workshop)  # not this workshop
    client.force_login(mechanic)

    response = client.get(reverse('mechanic_dashboard'))

    assert response.context['workshop'].name == 'Central Workshop'
    assert response.context['upcoming_count'] == 2
    assert response.context['assigned_count'] == 1
    assert len(response.context['next_bookings']) == 2
    assert 'Central Workshop' in response.content.decode()
    assert reverse('vehicles:list') in response.content.decode()


def test_mechanic_without_a_workshop_is_told_to_ask_an_admin(client, make_user):
    drifter = make_user('drifter', User.Role.MECHANIC)
    drifter.workshop = None
    drifter.save()
    client.force_login(drifter)

    response = client.get(reverse('mechanic_dashboard'))

    assert response.status_code == 200
    assert "aren't assigned to a workshop" in response.content.decode()
    assert response.context['upcoming_count'] == 0


def test_admin_dashboard_shows_pending_upcoming_and_vehicle_counts(client, admin_user, customer, vehicle, make_booking):
    make_booking(customer, vehicle)
    make_booking(customer, vehicle, time=datetime.time(11, 0), status='CONFIRMED')
    client.force_login(admin_user)

    response = client.get(reverse('admin_dashboard'))

    assert response.context['pending_count'] == 1
    assert response.context['upcoming_count'] == 2
    assert response.context['vehicle_count'] == 1
    assert '?status=PENDING' in response.content.decode()


def test_admin_dashboard_summarises_each_workshop(client, admin_user, make_user, workshop, other_workshop, customer, vehicle, make_booking):
    make_user('m1', User.Role.MECHANIC)
    make_user('m2', User.Role.MECHANIC)
    make_booking(customer, vehicle)
    client.force_login(admin_user)

    response = client.get(reverse('admin_dashboard'))

    rows = {row['workshop'].name: row for row in response.context['workshop_rows']}
    assert rows['Central Workshop']['mechanics'] == 2
    assert rows['Central Workshop']['upcoming'] == 1
    assert rows['North Workshop']['mechanics'] == 0
    assert rows['North Workshop']['upcoming'] == 0
    assert response.context['workshop_count'] == 2


def test_admin_user_table_shows_each_mechanics_workshop(client, admin_user, mechanic):
    client.force_login(admin_user)
    body = client.get(reverse('admin_dashboard')).content.decode()
    assert 'Central Workshop' in body


# ---------------------------------------------------------------- the parts warehouse


def test_warehouse_staff_dashboard_is_about_stock_not_bookings(client, warehouse_staff, warehouse, customer, vehicle, make_booking, make_part, make_stock):
    make_booking(customer, vehicle, workshop=warehouse)  # an old booking from before it became the warehouse
    low = make_part('LOW-1', universal=True)
    make_stock(warehouse, low, quantity=1, reorder_level=10)
    client.force_login(warehouse_staff)

    response = client.get(reverse('mechanic_dashboard'))

    body = response.content.decode()
    assert response.status_code == 200
    assert response.context['is_warehouse'] is True
    assert response.context['upcoming_count'] == 0
    assert response.context['low_stock_count'] == 1
    assert '(parts warehouse)' in body
    assert 'Low or out of stock' in body and 'Find parts' in body
    assert 'Upcoming bookings' not in body and 'Next bookings' not in body
    assert 'Job cards' not in body and 'Find a vehicle' not in body


def test_a_normal_mechanic_dashboard_is_unchanged_by_the_warehouse(client, mechanic, warehouse):
    client.force_login(mechanic)

    response = client.get(reverse('mechanic_dashboard'))

    assert response.context['is_warehouse'] is False
    body = response.content.decode()
    assert 'Upcoming bookings at your workshop' in body and 'Find a vehicle' in body


def test_admin_dashboard_lists_the_warehouse_separately(client, admin_user, workshop, other_workshop, warehouse, make_part, make_stock):
    make_stock(warehouse, make_part('A', universal=True))
    make_stock(warehouse, make_part('B', universal=True))
    client.force_login(admin_user)

    response = client.get(reverse('admin_dashboard'))

    assert response.context['workshop_count'] == 2  # the warehouse is not one of the workshops that take bookings
    assert len(response.context['workshop_rows']) == 3
    assert response.context['warehouse'] == warehouse
    assert response.context['warehouse_stock_count'] == 2
    body = response.content.decode()
    assert 'Parts warehouse stock' in body
    assert f"{reverse('inventory:stock')}?workshop={warehouse.pk}" in body
    assert 'No bookings' not in body  # the warehouse row doesn't talk about bookings at all


def test_admin_dashboard_without_a_warehouse_has_no_warehouse_card(client, admin_user, workshop):
    client.force_login(admin_user)

    response = client.get(reverse('admin_dashboard'))

    assert response.context['warehouse'] is None
    assert 'Parts warehouse stock' not in response.content.decode()


def test_the_warehouse_row_has_no_hours_mechanics_or_bookings(client, admin_user, workshop, warehouse, make_user):
    make_user('m1', User.Role.MECHANIC)
    client.force_login(admin_user)

    body = client.get(reverse('admin_dashboard')).content.decode()
    rows = body.split('<tbody>')[1].split('</tbody>')[0].split('<tr>')[1:]
    warehouse_row = next(row for row in rows if 'Parts Warehouse' in row)
    workshop_row = next(row for row in rows if 'Central Workshop' in row)

    assert warehouse_row.count('Not applicable') == 3  # hours, mechanics and upcoming bookings
    assert 'Monday' not in warehouse_row and 'bookings' not in warehouse_row.lower()
    assert 'Monday to Friday' in workshop_row and 'Not applicable' not in workshop_row  # workshops are unchanged


def test_analytics_is_global_for_admin_and_limited_to_mechanics_workshop(
    client, admin_user, mechanic, other_workshop, customer, make_booking, make_user, workshop,
):
    other_mechanic = make_user('other-mechanic', User.Role.MECHANIC, workshop=other_workshop)
    own_booking = make_booking(
        customer, status='COMPLETED', workshop=workshop, mechanic=mechanic,
        service_type='Oil Change',
    )
    own_job = JobCard.objects.create(
        booking=own_booking, mechanic=mechanic, labor_charge=Decimal('50.00'),
    )
    JobPart.objects.create(
        job_card=own_job, name='Oil filter', source=JobPart.Source.MANUAL, quantity=2,
        unit_cost=Decimal('10.00'), unit_price=Decimal('20.00'),
        freight_charge=Decimal('5.00'),
    )
    other_booking = make_booking(
        customer, status='COMPLETED', workshop=other_workshop, mechanic=other_mechanic,
        service_type='Transmission Repair',
    )
    JobCard.objects.create(
        booking=other_booking, mechanic=other_mechanic, labor_charge=Decimal('100.00'),
    )
    make_booking(customer, workshop=other_workshop, mechanic=other_mechanic, service_type='Inspection')

    client.force_login(admin_user)
    admin_response = client.get(reverse('analytics'))
    assert admin_response.status_code == 200
    assert admin_response.context['booking_count'] == 3
    assert admin_response.context['completed_job_count'] == 2
    assert admin_response.context['revenue'] == Decimal('195.00')
    assert admin_response.context['average_invoice'] == Decimal('97.50')
    assert {row['workshop'].pk for row in admin_response.context['workshop_rows']} >= {
        workshop.pk, other_workshop.pk,
    }

    client.force_login(mechanic)
    mechanic_response = client.get(reverse('analytics'))
    assert mechanic_response.status_code == 200
    assert mechanic_response.context['booking_count'] == 1
    assert mechanic_response.context['completed_job_count'] == 1
    assert mechanic_response.context['revenue'] == Decimal('95.00')
    assert 'Workshop performance' not in mechanic_response.content.decode()
    assert 'Transmission Repair' not in mechanic_response.content.decode()


def test_customers_cannot_access_analytics(client, customer):
    client.force_login(customer)
    assert client.get(reverse('analytics')).status_code == 403
