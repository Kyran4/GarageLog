import io

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from jobs.models import SupplierOrder

from .models import Part, StockItem, StockTransferRequest

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


# ---------------------------------------------------------------- the parts warehouse


def test_search_shows_what_the_warehouse_holds_beside_the_workshops_own_stock(
        client, mechanic, workshop, warehouse, corolla_parts, make_stock):
    make_stock(workshop, corolla_parts['filter_old'], quantity=2)
    make_stock(warehouse, corolla_parts['filter_old'], quantity=120)
    make_stock(warehouse, corolla_parts['oil'], quantity=0)
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'))
    body = response.content.decode()
    held = {part.part_number: part.warehouse_stock for part in response.context['parts']}

    assert response.context['warehouse'] == warehouse
    assert 'At Parts Warehouse' in body
    assert held['FIL-OLD'].quantity == 120
    assert held['FIL-NEW'] is None
    assert '120 in stock' in body and 'Not stocked' in body and 'Out of stock' in body


def test_there_is_no_warehouse_column_when_there_is_no_warehouse(client, mechanic, corolla_parts):
    client.force_login(mechanic)

    response = client.get(reverse('inventory:search'))

    assert response.context['warehouse'] is None
    assert 'At Parts Warehouse' not in response.content.decode()


def test_warehouse_staff_see_the_warehouse_stock_in_the_main_column_without_a_duplicate(
        client, warehouse_staff, warehouse, corolla_parts, make_stock):
    make_stock(warehouse, corolla_parts['filter_old'], quantity=90)
    client.force_login(warehouse_staff)

    response = client.get(reverse('inventory:search'))

    assert response.context['workshop'] == warehouse
    assert response.context['warehouse'] is None
    body = response.content.decode()
    assert '90 in stock' in body
    assert 'At Parts Warehouse' not in body


def test_admin_sees_the_warehouse_column_when_looking_at_a_workshop_and_labels_it_in_the_picker(
        client, admin_user, workshop, warehouse, corolla_parts, make_stock):
    make_stock(warehouse, corolla_parts['filter_old'], quantity=60)
    client.force_login(admin_user)

    response = client.get(reverse('inventory:search'), {'workshop': workshop.pk})

    assert response.context['warehouse'] == warehouse
    assert 'Parts Warehouse (parts warehouse)' in response.content.decode()


def test_part_detail_shows_a_mechanic_their_own_stock_and_the_warehouses_but_not_other_workshops(
        client, mechanic, workshop, other_workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    mine = make_stock(workshop, part, quantity=3)
    theirs = make_stock(other_workshop, part, quantity=77)
    held = make_stock(warehouse, part, quantity=150)
    client.force_login(mechanic)

    response = client.get(reverse('inventory:detail', kwargs={'pk': part.pk}))

    rows = {row.workshop.name: row for row in response.context['stock_rows']}
    assert set(rows) == {'Central Workshop', 'Parts Warehouse'}
    assert rows['Central Workshop'].can_edit and not rows['Parts Warehouse'].can_edit
    body = response.content.decode()
    assert 'Parts warehouse' in body and '150' in body
    assert reverse('inventory:stock_edit', kwargs={'pk': mine.pk}) in body
    assert reverse('inventory:stock_edit', kwargs={'pk': held.pk}) not in body  # read-only for a workshop mechanic
    assert reverse('inventory:stock_edit', kwargs={'pk': theirs.pk}) not in body
    assert 'North Workshop' not in body


def test_part_detail_lets_an_admin_edit_every_location_including_the_warehouse(
        client, admin_user, workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    make_stock(workshop, part)
    held = make_stock(warehouse, part)
    client.force_login(admin_user)

    response = client.get(reverse('inventory:detail', kwargs={'pk': part.pk}))

    assert all(row.can_edit for row in response.context['stock_rows'])
    assert reverse('inventory:stock_edit', kwargs={'pk': held.pk}) in response.content.decode()


def test_a_workshop_mechanic_cannot_change_the_warehouses_stock(client, mechanic, warehouse, corolla_parts, make_stock):
    held = make_stock(warehouse, corolla_parts['filter_old'], quantity=100)
    client.force_login(mechanic)
    url = reverse('inventory:stock_edit', kwargs={'pk': held.pk})

    assert client.get(url).status_code == 404
    assert client.post(url, {'quantity': 0, 'reorder_level': 0}).status_code == 404
    held.refresh_from_db()
    assert held.quantity == 100


def test_warehouse_staff_manage_the_warehouses_stock(client, warehouse_staff, warehouse, corolla_parts, make_stock):
    held = make_stock(warehouse, corolla_parts['filter_old'], quantity=100)
    client.force_login(warehouse_staff)

    listing = client.get(reverse('inventory:stock'))
    assert list(listing.context['items']) == [held]
    assert 'Parts warehouse' in listing.content.decode()
    assert "doesn't take customer bookings" in listing.content.decode().replace('&#x27;', "'")
    assert (
        f'{reverse("supplier_stock_order_create")}?part={held.part_id}&amp;quantity=1'
        in listing.content.decode()
    )

    response = client.post(
        reverse('inventory:stock_edit', kwargs={'pk': held.pk}), {'quantity': 80, 'reorder_level': 20},
    )

    assert response.status_code == 302
    held.refresh_from_db()
    assert held.quantity == 80


def test_warehouse_staff_can_order_part_from_stock_detail(client, warehouse_staff, warehouse, corolla_parts, make_stock):
    held = make_stock(warehouse, corolla_parts['filter_old'], quantity=100)
    client.force_login(warehouse_staff)

    response = client.get(
        reverse('inventory:detail', kwargs={'pk': held.part_id})
    )

    assert response.status_code == 200
    assert (
        f'{reverse("supplier_stock_order_create")}?part={held.part_id}&amp;quantity=1'
        in response.content.decode()
    )


def test_warehouse_stock_list_shows_outstanding_supplier_order_quantity(
    client, warehouse_staff, warehouse, corolla_parts, make_stock
):
    part = corolla_parts['filter_old']
    make_stock(warehouse, part, quantity=0)
    order = SupplierOrder.objects.create(
        part=part,
        quantity=6,
        supplier='Test supplier',
        unit_cost='12.50',
        ordered_by=warehouse_staff,
    )
    client.force_login(warehouse_staff)

    response = client.get(reverse('inventory:stock'))

    assert response.status_code == 200
    assert 'On order: 6' in response.content.decode()

    order.received_at = timezone.now()
    order.save(update_fields=['received_at'])
    response = client.get(reverse('inventory:stock'))
    assert 'On order: 6' not in response.content.decode()


def test_the_admins_stock_picker_labels_the_warehouse(client, admin_user, workshop, warehouse):
    client.force_login(admin_user)

    body = client.get(reverse('inventory:stock'), {'workshop': warehouse.pk}).content.decode()

    assert 'Parts Warehouse (parts warehouse)' in body
    assert 'Parts warehouse' in body


def test_admins_can_open_the_warehouse_transfer_form_with_a_selected_workshop_and_part(
        client, admin_user, other_workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    make_stock(warehouse, part, quantity=7)
    client.force_login(admin_user)

    response = client.get(
        reverse('inventory:stock_transfer'),
        {'workshop': other_workshop.pk, 'part': part.pk},
    )

    assert response.status_code == 200
    assert str(response.context['form']['workshop'].value()) == str(other_workshop.pk)
    assert str(response.context['form']['part'].value()) == str(part.pk)
    assert 'available: 7' in response.content.decode()


def test_admins_request_warehouse_stock_and_wait_for_warehouse_approval(
        client, admin_user, warehouse_staff, workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    warehouse_item = make_stock(warehouse, part, quantity=8)
    workshop_item = make_stock(workshop, part, quantity=2, reorder_level=4, bin_location='A2-1')
    client.force_login(admin_user)

    response = client.post(reverse('inventory:stock_transfer'), {
        'workshop': workshop.pk,
        'part': part.pk,
        'quantity': 3,
    })

    assert response.status_code == 302
    assert response.url == reverse('supplier_order_list')
    warehouse_item.refresh_from_db()
    workshop_item.refresh_from_db()
    transfer_request = StockTransferRequest.objects.get()
    assert transfer_request.status == StockTransferRequest.Status.PENDING
    assert transfer_request.requested_by == admin_user
    assert (warehouse_item.quantity, workshop_item.quantity) == (8, 2)

    client.force_login(warehouse_staff)
    response = client.post(reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk}))

    assert response.status_code == 302
    warehouse_item.refresh_from_db()
    workshop_item.refresh_from_db()
    transfer_request.refresh_from_db()
    assert warehouse_item.quantity == 5
    assert (workshop_item.quantity, workshop_item.reorder_level, workshop_item.bin_location) == (5, 4, 'A2-1')
    assert transfer_request.status == StockTransferRequest.Status.APPROVED
    assert transfer_request.resolved_by == warehouse_staff


def test_approved_transfer_creates_workshop_stock_record_when_needed(
        client, admin_user, warehouse_staff, workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    warehouse_item = make_stock(warehouse, part, quantity=3)
    client.force_login(admin_user)

    response = client.post(reverse('inventory:stock_transfer'), {
        'workshop': workshop.pk,
        'part': part.pk,
        'quantity': 2,
    })

    assert response.status_code == 302
    transfer_request = StockTransferRequest.objects.get()
    assert transfer_request.status == StockTransferRequest.Status.PENDING
    assert not StockItem.objects.filter(workshop=workshop, part=part).exists()

    client.force_login(warehouse_staff)
    client.post(reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk}))
    warehouse_item.refresh_from_db()
    workshop_item = StockItem.objects.get(workshop=workshop, part=part)
    assert warehouse_item.quantity == 1
    assert workshop_item.quantity == 2
    assert workshop_item.unit_price is None


def test_warehouse_worker_cannot_approve_when_warehouse_stock_is_no_longer_sufficient(
        client, admin_user, warehouse_staff, workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    warehouse_item = make_stock(warehouse, part, quantity=2)
    client.force_login(admin_user)

    response = client.post(reverse('inventory:stock_transfer'), {
        'workshop': workshop.pk,
        'part': part.pk,
        'quantity': 2,
    })

    assert response.status_code == 302
    transfer_request = StockTransferRequest.objects.get()
    warehouse_item.quantity = 1
    warehouse_item.save(update_fields=['quantity'])

    client.force_login(warehouse_staff)
    response = client.post(reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk}))

    assert response.status_code == 302
    warehouse_item.refresh_from_db()
    transfer_request.refresh_from_db()
    assert warehouse_item.quantity == 1
    assert transfer_request.status == StockTransferRequest.Status.PENDING
    assert not StockItem.objects.filter(workshop=workshop, part=part).exists()


def test_admin_transfer_cannot_use_the_parts_warehouse_as_the_destination(
        client, admin_user, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    warehouse_item = make_stock(warehouse, part, quantity=2)
    client.force_login(admin_user)

    response = client.post(reverse('inventory:stock_transfer'), {
        'workshop': warehouse.pk,
        'part': part.pk,
        'quantity': 1,
    })

    assert response.status_code == 200
    assert 'workshop' in response.context['form'].errors
    warehouse_item.refresh_from_db()
    assert warehouse_item.quantity == 2
    assert StockItem.objects.filter(workshop=warehouse, part=part).count() == 1


def test_only_parts_warehouse_workers_can_approve_transfers(
        client, mechanic, customer, admin_user, warehouse_staff, warehouse, corolla_parts, make_stock):
    make_stock(warehouse, corolla_parts['filter_old'])
    transfer_request = StockTransferRequest.objects.create(
        workshop=mechanic.workshop,
        part=corolla_parts['filter_old'],
        quantity=1,
        requested_by=admin_user,
    )
    url = reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk})

    for user in (mechanic, customer, admin_user):
        client.force_login(user)
        assert client.get(url).status_code == 403
        assert client.post(url).status_code == 403

    client.force_login(warehouse_staff)
    assert client.post(url).status_code == 302
    transfer_request.refresh_from_db()
    assert transfer_request.status == StockTransferRequest.Status.APPROVED


def test_warehouse_worker_can_reject_a_resupply_request_without_moving_stock(
        client, warehouse_staff, admin_user, workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    warehouse_item = make_stock(warehouse, part, quantity=3)
    transfer_request = StockTransferRequest.objects.create(
        workshop=workshop,
        part=part,
        quantity=2,
        requested_by=admin_user,
    )
    client.force_login(warehouse_staff)

    response = client.post(reverse('inventory:stock_transfer_reject', kwargs={'pk': transfer_request.pk}))

    assert response.status_code == 302
    transfer_request.refresh_from_db()
    warehouse_item.refresh_from_db()
    assert transfer_request.status == StockTransferRequest.Status.REJECTED
    assert transfer_request.resolved_by == warehouse_staff
    assert warehouse_item.quantity == 3
    assert not StockItem.objects.filter(workshop=workshop, part=part).exists()


def test_warehouse_orders_page_shows_requests_and_only_warehouse_workers_get_decision_buttons(
        client, admin_user, warehouse_staff, workshop, corolla_parts):
    transfer_request = StockTransferRequest.objects.create(
        workshop=workshop,
        part=corolla_parts['filter_old'],
        quantity=2,
        requested_by=admin_user,
    )
    url = reverse('supplier_order_list')

    client.force_login(admin_user)
    admin_body = client.get(url).content.decode()
    assert 'Workshop resupply requests' in admin_body
    assert 'Pending approval' in admin_body
    assert reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk}) not in admin_body

    client.force_login(warehouse_staff)
    worker_body = client.get(url).content.decode()
    assert reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk}) in worker_body
    assert reverse('inventory:stock_transfer_reject', kwargs={'pk': transfer_request.pk}) in worker_body


def test_a_resupply_request_cannot_be_approved_more_than_once(
        client, warehouse_staff, admin_user, workshop, warehouse, corolla_parts, make_stock):
    part = corolla_parts['filter_old']
    warehouse_item = make_stock(warehouse, part, quantity=5)
    transfer_request = StockTransferRequest.objects.create(
        workshop=workshop,
        part=part,
        quantity=2,
        requested_by=admin_user,
    )
    client.force_login(warehouse_staff)
    url = reverse('inventory:stock_transfer_approve', kwargs={'pk': transfer_request.pk})

    assert client.post(url).status_code == 302
    assert client.post(url).status_code == 302

    warehouse_item.refresh_from_db()
    transfer_request.refresh_from_db()
    assert warehouse_item.quantity == 3
    assert StockItem.objects.get(workshop=workshop, part=part).quantity == 2
    assert transfer_request.status == StockTransferRequest.Status.APPROVED


def test_workshop_stock_navigation_exposes_direct_resupply_only_to_admins(
        client, admin_user, mechanic, other_workshop):
    client.force_login(admin_user)
    admin_body = client.get(reverse('inventory:stock'), {'workshop': other_workshop.pk}).content.decode()
    assert f'href="{reverse("inventory:stock_transfer")}?workshop={other_workshop.pk}"' in admin_body

    client.force_login(mechanic)
    mechanic_body = client.get(reverse('inventory:stock')).content.decode()
    assert reverse('inventory:stock_transfer') not in mechanic_body
