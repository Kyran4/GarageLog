import pytest
from django.urls import reverse

from accounts.models import User

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
    body = response.content.decode()
    assert 'customer@example.com' in body
    assert 'mechanic@example.com' in body


def test_admin_dashboard_paginates(client, admin_user, make_user):
    for number in range(25):
        make_user(f'bulk{number}')
    client.force_login(admin_user)

    first = client.get(reverse('admin_dashboard'))
    second = client.get(reverse('admin_dashboard') + '?page=2')

    assert len(first.context['users']) == 20
    assert len(second.context['users']) == 6


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
