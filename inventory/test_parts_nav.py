import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_a_mechanic_gets_a_button_to_their_own_workshops_stock(client, mechanic, workshop, other_workshop):
    client.force_login(mechanic)

    body = client.get(reverse('inventory:search')).content.decode()

    assert 'Central Workshop stock</a>' in body
    assert f'href="{reverse("inventory:stock")}"' in body  # no workshop chosen in the link: a mechanic only ever has their own
    assert 'North Workshop stock' not in body


def test_the_button_leads_to_the_mechanics_own_stock(client, mechanic, workshop, other_workshop, make_part, make_stock):
    part = make_part('P-1', universal=True)
    mine = make_stock(workshop, part)
    make_stock(other_workshop, part)
    client.force_login(mechanic)

    response = client.get(reverse('inventory:stock'))

    assert list(response.context['items']) == [mine]


def test_admins_do_not_get_the_button(client, admin_user, workshop, other_workshop):
    client.force_login(admin_user)

    response = client.get(reverse('inventory:search'))
    body = response.content.decode()

    assert response.status_code == 200
    assert 'Central Workshop stock' not in body and 'North Workshop stock' not in body
    assert 'Workshop stock</a>' not in body
    assert f'href="{reverse("inventory:stock")}' not in body.split('<main', 1)[1]  # nothing on the page links to a stock list


def test_admins_still_see_the_workshop_picker_for_choosing_whose_stock_to_show(client, admin_user, workshop, other_workshop):
    client.force_login(admin_user)

    body = client.get(reverse('inventory:search')).content.decode()

    assert 'Workshop stock to show' in body


def test_customers_cannot_reach_the_parts_tab_at_all(client, customer, workshop):
    client.force_login(customer)
    assert client.get(reverse('inventory:search')).status_code == 403


def test_a_mechanic_with_no_workshop_gets_no_button(client, make_user):
    from accounts.models import User

    drifter = make_user('drifter', User.Role.MECHANIC)
    drifter.workshop = None
    drifter.save()
    client.force_login(drifter)

    body = client.get(reverse('inventory:search')).content.decode()

    assert 'stock</a>' not in body.split('<main', 1)[1].split('<form', 1)[0]
