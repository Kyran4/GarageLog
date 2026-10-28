import io

import pytest
from django.core.management import call_command
from django.urls import reverse

from accounts.models import User

from .models import Part, StockItem

pytestmark = pytest.mark.django_db


def listed(response):
    return sorted(part.part_number for part in response.context['parts'])


@pytest.fixture
def corolla_parts(make_part):
    """A small catalogue: parts for two Corolla generations, a Mazda part and a universal oil."""
    return {
        'filter_old': make_part('FIL-OLD', 'Oil filter - Corolla 2007-2018', fits=[('Toyota', 'Corolla', 2007, 2018)]),
        'filter_new': make_part('FIL-NEW', 'Oil filter - Corolla 2019-2024', fits=[('Toyota', 'Corolla', 2019, 2024)]),
        'mazda': make_part('FIL-MZ', 'Oil filter - Mazda3', fits=[('Mazda', 'Mazda3', 2009, 2018)]),
        'oil': make_part('OIL-UNI', 'Engine oil 5W-30 4L', category='FLUIDS', universal=True),
    }


# ---------------------------------------------------------------- access


URLS = [
    ('inventory:search', None), ('inventory:detail', 'part'), ('inventory:stock', None),
    ('inventory:stock_add', None), ('inventory:stock_edit', 'stock'), ('inventory:stock_delete', 'stock'),
]


def url_for(name, kind, part, stock):
    pk = {'part': part.pk, 'stock': stock.pk}.get(kind)
    return reverse(name, kwargs={'pk': pk} if pk else {})


@pytest.mark.parametrize('name, kind', URLS)
def test_anonymous_users_are_sent_to_login(client, make_part, make_stock, workshop, name, kind):
    part = make_part()
    stock = make_stock(workshop, part)
    url = url_for(name, kind, part, stock)

    response = client.get(url)

    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next={url}"


@pytest.mark.parametrize('name, kind', URLS)
def test_customers_have_no_access_to_the_parts_library(client, customer, make_part, make_stock, workshop, name, kind):
    part = make_part()
    stock = make_stock(workshop, part)
    client.force_login(customer)

    assert client.get(url_for(name, kind, part, stock)).status_code == 403


@pytest.mark.parametrize('name, kind', URLS)
def test_mechanics_and_admins_can_open_every_page(client, mechanic, admin_user, make_part, make_stock, workshop, name, kind):
    part = make_part()
    stock = make_stock(workshop, part)
    for user in (mechanic, admin_user):
        client.force_login(user)
        assert client.get(url_for(name, kind, part, stock)).status_code == 200


def test_navbar_shows_parts_to_staff_only(client, customer, mechanic, admin_user):
    def has_parts_link(user):
        client.force_login(user)
        return reverse('inventory:search') in client.get(reverse('home')).content.decode()

    assert has_parts_link(mechanic) and has_parts_link(admin_user)
    assert not has_parts_link(customer)


# ---------------------------------------------------------------- searching


def test_with_no_search_every_part_is_listed_a_page_at_a_time(client, mechanic):
    call_command('import_parts', stdout=io.StringIO())
    client.force_login(mechanic)

    first = client.get(reverse('inventory:search'))
    last = client.get(reverse('inventory:search') + '?page=8')

    assert first.context['page_obj'].paginator.count == 200
    assert len(first.context['parts']) == 25
    assert len(last.context['parts']) == 25


def test_searching_by_make_and_model_lists_matching_parts_before_universal_ones(client, mechanic, corolla_parts):
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'), {'make': 'toyota', 'model': 'Corolla', 'year': 2012})

    assert listed(response) == ['FIL-OLD', 'OIL-UNI']
    assert [part.part_number for part in response.context['parts']] == ['FIL-OLD', 'OIL-UNI']  # specific first


def test_searching_by_make_alone_covers_every_model_and_year(client, mechanic, corolla_parts):
    client.force_login(mechanic)
    response = client.get(reverse('inventory:search'), {'make': 'Toyota'})
    assert listed(response) == ['FIL-NEW', 'FIL-OLD', 'OIL-UNI']


def test_a_plate_in_the_system_uses_that_vehicles_make_model_and_year(client, mechanic, customer, vehicle, make_vehicle, corolla_parts):
    vehicle.year = 2012  # the fixture vehicle is a 2015 Toyota Corolla
    vehicle.save()
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'), {'plate': 'abc 123'})

    assert listed(response) == ['FIL-OLD', 'OIL-UNI']
    assert response.context['vehicle'] == vehicle
    body = response.content.decode()
    assert 'Showing parts for' in body and '2012 Toyota Corolla' in body

    vehicle.year = 2021  # a newer Corolla gets the newer filter
    vehicle.save()
    assert listed(client.get(reverse('inventory:search'), {'plate': 'ABC123'})) == ['FIL-NEW', 'OIL-UNI']


def test_a_plate_takes_priority_over_a_typed_make_and_model(client, mechanic, vehicle, corolla_parts):
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'), {'plate': 'ABC123', 'make': 'Mazda', 'model': 'Mazda3'})

    assert 'FIL-MZ' not in listed(response)
    assert 'FIL-OLD' in listed(response)


def test_a_plate_that_is_not_in_the_system_is_explained_and_lists_nothing(client, mechanic, corolla_parts):
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'), {'plate': 'NOPE99'})

    assert listed(response) == []
    assert 'Search by make and model instead' in response.content.decode()
    assert 'id="form-errors"' in response.content.decode()


def test_searching_by_name_part_number_brand_and_category(client, mechanic, make_part, corolla_parts):
    make_part('BP-1', 'Front brake pads', category='BRAKES', brand='Acme', universal=True)
    client.force_login(mechanic)

    assert listed(client.get(reverse('inventory:search'), {'q': 'brake'})) == ['BP-1']
    assert listed(client.get(reverse('inventory:search'), {'q': 'fil-mz'})) == ['FIL-MZ']
    assert listed(client.get(reverse('inventory:search'), {'q': 'acme'})) == ['BP-1']
    assert listed(client.get(reverse('inventory:search'), {'category': 'FLUIDS'})) == ['OIL-UNI']
    assert listed(client.get(reverse('inventory:search'), {'make': 'Toyota', 'q': 'old'})) == ['FIL-OLD']


def test_invalid_year_is_reported(client, mechanic, corolla_parts):
    client.force_login(mechanic)
    response = client.get(reverse('inventory:search'), {'year': 1700})
    assert 'year' in response.context['form'].errors
    assert listed(response) == []


def test_search_results_show_the_mechanics_workshops_stock_only(
        client, mechanic, workshop, other_workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'], quantity=7, bin_location='A1-2')
    make_stock(other_workshop, corolla_parts['filter_old'], quantity=99)  # not this mechanic's workshop
    make_stock(workshop, corolla_parts['oil'], quantity=0)
    make_stock(workshop, corolla_parts['mazda'], quantity=1, reorder_level=2)
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'))
    body = response.content.decode()
    stock = {part.part_number: part.workshop_stock for part in response.context['parts']}

    assert stock['FIL-OLD'].quantity == 7
    assert stock['FIL-NEW'] is None
    assert '7 in stock' in body and 'Bin A1-2' in body
    assert 'Out of stock' in body and 'Low: 1' in body and 'Not stocked' in body
    assert '99' not in body


def test_in_stock_only_filter(client, mechanic, workshop, other_workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'], quantity=3)
    make_stock(workshop, corolla_parts['oil'], quantity=0)  # recorded, but none on the shelf
    make_stock(other_workshop, corolla_parts['mazda'], quantity=10)  # in stock, but elsewhere
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'), {'in_stock': 'on'})

    assert listed(response) == ['FIL-OLD']


def test_admin_chooses_which_workshops_stock_to_see(client, admin_user, workshop, other_workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'], quantity=3)
    make_stock(other_workshop, corolla_parts['filter_old'], quantity=8)
    client.force_login(admin_user)

    default = client.get(reverse('inventory:search'))
    north = client.get(reverse('inventory:search'), {'workshop': other_workshop.pk})
    only_north_in_stock = client.get(
        reverse('inventory:search'), {'workshop': other_workshop.pk, 'in_stock': 'on', 'make': 'Toyota'})

    assert default.context['workshop'] == workshop  # the first workshop by name
    assert north.context['workshop'] == other_workshop
    assert {p.part_number: p.workshop_stock for p in north.context['parts']}['FIL-OLD'].quantity == 8
    assert listed(only_north_in_stock) == ['FIL-OLD']


def test_pagination_keeps_the_search(client, mechanic):
    call_command('import_parts', stdout=io.StringIO())
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'), {'category': 'FILTERS'})

    assert 'category=FILTERS&amp;page=2' in response.content.decode()


# ---------------------------------------------------------------- part detail


def test_part_detail_lists_what_it_fits(client, mechanic, corolla_parts):
    client.force_login(mechanic)

    body = client.get(reverse('inventory:detail', kwargs={'pk': corolla_parts['filter_old'].pk})).content.decode()
    universal = client.get(reverse('inventory:detail', kwargs={'pk': corolla_parts['oil'].pk})).content.decode()

    assert 'Toyota Corolla 2007-2018' in body
    assert 'universal part' in universal


def test_part_detail_shows_a_mechanic_only_their_workshops_stock(
        client, mechanic, workshop, other_workshop, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    make_stock(workshop, part, quantity=4)
    make_stock(other_workshop, part, quantity=77)
    client.force_login(mechanic)

    response = client.get(reverse('inventory:detail', kwargs={'pk': part.pk}))

    assert [item.workshop for item in response.context['stock_rows']] == [workshop]
    assert 'North Workshop' not in response.content.decode()
    assert response.context['already_stocked'] is True


def test_part_detail_shows_an_admin_every_workshop(client, admin_user, workshop, other_workshop, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    make_stock(workshop, part, quantity=4)
    make_stock(other_workshop, part, quantity=77)
    client.force_login(admin_user)

    response = client.get(reverse('inventory:detail', kwargs={'pk': part.pk}))

    assert [item.workshop.name for item in response.context['stock_rows']] == ['Central Workshop', 'North Workshop']


def test_part_detail_offers_to_add_a_part_that_is_not_stocked(client, mechanic, corolla_parts):
    part = corolla_parts['filter_old']
    client.force_login(mechanic)

    body = client.get(reverse('inventory:detail', kwargs={'pk': part.pk})).content.decode()

    assert f"{reverse('inventory:stock_add')}?part={part.pk}" in body


# ---------------------------------------------------------------- a workshop's stock


def test_stock_list_shows_only_the_mechanics_workshop(client, mechanic, workshop, other_workshop, corolla_parts, make_stock):
    mine = make_stock(workshop, corolla_parts['filter_old'])
    make_stock(other_workshop, corolla_parts['mazda'])
    client.force_login(mechanic)

    response = client.get(reverse('inventory:stock'))

    assert list(response.context['items']) == [mine]
    assert response.context['workshop'] == workshop
    assert response.context['workshops'] is None  # mechanics cannot switch workshop


def test_stock_list_low_stock_filter_and_counts(client, mechanic, workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'], quantity=10, reorder_level=2)
    low = make_stock(workshop, corolla_parts['filter_new'], quantity=2, reorder_level=2)
    out = make_stock(workshop, corolla_parts['oil'], quantity=0)
    client.force_login(mechanic)

    response = client.get(reverse('inventory:stock'), {'low': '1'})

    assert set(response.context['items']) == {low, out}
    assert response.context['total_count'] == 3
    assert response.context['low_count'] == 2


def test_stock_list_search_and_category_filters(client, mechanic, workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'])
    oil = make_stock(workshop, corolla_parts['oil'])
    client.force_login(mechanic)

    assert list(client.get(reverse('inventory:stock'), {'q': 'engine'}).context['items']) == [oil]
    assert list(client.get(reverse('inventory:stock'), {'category': 'FLUIDS'}).context['items']) == [oil]


def test_admin_can_switch_between_workshops_stock(client, admin_user, workshop, other_workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'])
    north = make_stock(other_workshop, corolla_parts['mazda'])
    client.force_login(admin_user)

    response = client.get(reverse('inventory:stock'), {'workshop': other_workshop.pk})

    assert list(response.context['items']) == [north]
    assert [w.name for w in response.context['workshops']] == ['Central Workshop', 'North Workshop']


def test_mechanic_without_a_workshop_sees_a_warning_and_no_stock(client, make_user, corolla_parts):
    drifter = make_user('drifter', User.Role.MECHANIC)
    drifter.workshop = None
    drifter.save()
    client.force_login(drifter)

    response = client.get(reverse('inventory:stock'))

    assert response.status_code == 200
    assert "aren't assigned to a workshop" in response.content.decode()
    assert client.get(reverse('inventory:stock_add')).status_code == 302


# ---------------------------------------------------------------- changing stock


def test_mechanic_adds_a_part_to_their_workshops_stock(client, mechanic, workshop, corolla_parts):
    part = corolla_parts['filter_old']
    client.force_login(mechanic)

    form = client.get(reverse('inventory:stock_add') + f'?part={part.pk}').context['form']
    assert str(form['part'].value()) == str(part.pk)  # opened from a search result or part page

    response = client.post(reverse('inventory:stock_add'), {
        'part': part.pk, 'quantity': 6, 'reorder_level': 3, 'unit_price': '', 'bin_location': 'B2-4',
    })

    assert response.status_code == 302
    assert response.url == reverse('inventory:stock')
    item = StockItem.objects.get()
    assert (item.workshop, item.part, item.quantity, item.reorder_level, item.unit_price, item.bin_location) == (
        workshop, part, 6, 3, None, 'B2-4')


def test_the_add_form_only_offers_parts_the_workshop_does_not_stock_yet(
        client, mechanic, workshop, other_workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'])
    make_stock(other_workshop, corolla_parts['mazda'])  # stocked elsewhere, still available here
    client.force_login(mechanic)

    form = client.get(reverse('inventory:stock_add')).context['form']

    offered = {part.part_number for part in form.fields['part'].queryset}
    assert offered == {'FIL-NEW', 'FIL-MZ', 'OIL-UNI'}


def test_a_part_cannot_be_added_twice_to_the_same_workshop(client, mechanic, workshop, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    make_stock(workshop, part)
    client.force_login(mechanic)

    response = client.post(reverse('inventory:stock_add'), {'part': part.pk, 'quantity': 1, 'reorder_level': 2})

    assert response.status_code == 200
    assert 'part' in response.context['form'].errors
    assert StockItem.objects.count() == 1


@pytest.mark.parametrize('overrides, bad_field', [
    ({'quantity': -1}, 'quantity'), ({'quantity': ''}, 'quantity'), ({'reorder_level': -2}, 'reorder_level'),
    ({'unit_price': '-3.00'}, 'unit_price'), ({'unit_price': 'cheap'}, 'unit_price'),
])
def test_stock_validation_errors(client, mechanic, corolla_parts, overrides, bad_field):
    client.force_login(mechanic)
    data = {'part': corolla_parts['filter_old'].pk, 'quantity': 1, 'reorder_level': 2, **overrides}

    response = client.post(reverse('inventory:stock_add'), data)

    assert response.status_code == 200
    assert bad_field in response.context['form'].errors
    assert not StockItem.objects.exists()


def test_a_mechanic_cannot_choose_the_workshop_when_adding_stock(
        client, mechanic, workshop, other_workshop, corolla_parts):
    client.force_login(mechanic)

    client.post(reverse('inventory:stock_add') + f'?workshop={other_workshop.pk}', {
        'part': corolla_parts['filter_old'].pk, 'quantity': 1, 'reorder_level': 2, 'workshop': other_workshop.pk,
    })

    assert StockItem.objects.get().workshop == workshop


def test_admin_adds_stock_to_the_chosen_workshop(client, admin_user, other_workshop, corolla_parts):
    client.force_login(admin_user)

    response = client.post(reverse('inventory:stock_add') + f'?workshop={other_workshop.pk}', {
        'part': corolla_parts['filter_old'].pk, 'quantity': 4, 'reorder_level': 1,
    })

    assert response.status_code == 302
    assert response.url == reverse('inventory:stock') + f'?workshop={other_workshop.pk}'
    assert StockItem.objects.get().workshop == other_workshop


def test_mechanic_updates_stock_and_sets_a_workshop_price(client, mechanic, workshop, corolla_parts, make_stock):
    item = make_stock(workshop, corolla_parts['filter_old'], quantity=5)
    client.force_login(mechanic)
    url = reverse('inventory:stock_edit', kwargs={'pk': item.pk})

    form = client.get(url).context['form']
    assert 'part' not in form.fields  # the part is fixed once stocked

    response = client.post(url, {'quantity': 2, 'reorder_level': 4, 'unit_price': '19.90', 'bin_location': 'C3-1'})

    assert response.status_code == 302
    item.refresh_from_db()
    assert (item.quantity, item.reorder_level, str(item.unit_price), item.bin_location) == (2, 4, '19.90', 'C3-1')
    assert item.is_low


def test_a_mechanic_cannot_edit_or_remove_another_workshops_stock(
        client, mechanic, other_workshop, corolla_parts, make_stock):
    theirs = make_stock(other_workshop, corolla_parts['mazda'], quantity=9)
    client.force_login(mechanic)

    for name in ('inventory:stock_edit', 'inventory:stock_delete'):
        url = reverse(name, kwargs={'pk': theirs.pk})
        assert client.get(url).status_code == 404
        assert client.post(url, {'quantity': 0, 'reorder_level': 0}).status_code == 404
    theirs.refresh_from_db()
    assert theirs.quantity == 9


def test_admin_can_edit_any_workshops_stock(client, admin_user, other_workshop, corolla_parts, make_stock):
    item = make_stock(other_workshop, corolla_parts['mazda'], quantity=9)
    client.force_login(admin_user)

    response = client.post(reverse('inventory:stock_edit', kwargs={'pk': item.pk}), {'quantity': 1, 'reorder_level': 2})

    assert response.status_code == 302
    assert response.url == reverse('inventory:stock') + f'?workshop={other_workshop.pk}'
    item.refresh_from_db()
    assert item.quantity == 1


def test_removing_stock_keeps_the_part_in_the_library(client, mechanic, workshop, corolla_parts, make_stock):
    item = make_stock(workshop, corolla_parts['filter_old'])
    client.force_login(mechanic)
    url = reverse('inventory:stock_delete', kwargs={'pk': item.pk})

    assert client.get(url).status_code == 200
    response = client.post(url)

    assert response.status_code == 302
    assert not StockItem.objects.exists()
    assert Part.objects.filter(part_number='FIL-OLD').exists()


# ---------------------------------------------------------------- dashboards


def test_mechanic_dashboard_counts_low_stock_at_their_workshop(
        client, mechanic, workshop, other_workshop, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'], quantity=10)
    make_stock(workshop, corolla_parts['filter_new'], quantity=1)
    make_stock(workshop, corolla_parts['oil'], quantity=0)
    make_stock(other_workshop, corolla_parts['mazda'], quantity=0)  # another workshop's problem
    client.force_login(mechanic)

    response = client.get(reverse('mechanic_dashboard'))

    assert response.context['low_stock_count'] == 2
    body = response.content.decode()
    assert reverse('inventory:search') in body
    assert reverse('inventory:stock') + '?low=1' in body


def test_admin_dashboard_counts_active_parts(client, admin_user, corolla_parts, make_part):
    make_part('OLD-1', is_active=False)
    client.force_login(admin_user)

    response = client.get(reverse('admin_dashboard'))

    assert response.context['part_count'] == 4
    assert reverse('inventory:search') in response.content.decode()
