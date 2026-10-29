import csv
import io
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import User
from vehicles.models import Vehicle

from .importer import parse_fitment, parse_years
from .management.commands.import_parts import DEFAULT_CSV
from .models import Part, PartFitment, StockItem, parts_matching
from .seeding import EMPTY, SAMPLE, seed_workshop_stock

pytestmark = pytest.mark.django_db

CSV_HEADER = 'part_number,name,brand,category,default_price,universal,fitment,description\n'


def write_csv(tmp_path, *rows):
    path = tmp_path / 'parts.csv'
    path.write_text(CSV_HEADER + '\n'.join(rows) + '\n', encoding='utf-8')
    return path


def numbers(parts):
    return sorted(part.part_number for part in parts)


# ---------------------------------------------------------------- matching parts to a vehicle


def test_a_part_matches_make_model_and_year(make_part):
    corolla = make_part('A', fits=[('Toyota', 'Corolla', 2007, 2018)])
    make_part('B', fits=[('Toyota', 'Corolla', 2019, 2024)])
    make_part('C', fits=[('Mazda', 'Mazda3', 2009, 2018)])

    assert numbers(parts_matching('Toyota', 'Corolla', 2012)) == ['A']
    assert numbers(parts_matching('Toyota', 'Corolla', 2020)) == ['B']
    assert numbers(parts_matching('Toyota', 'Corolla')) == ['A', 'B']  # no year: any year range
    assert numbers(parts_matching('Toyota')) == ['A', 'B']  # no model: any Toyota
    assert corolla in parts_matching('toyota', 'COROLLA', 2007)  # ignores case
    assert numbers(parts_matching('Toyota', 'Hilux', 2012)) == []


def test_year_ranges_include_both_ends_and_can_be_open_ended(make_part):
    make_part('RANGE', fits=[('Honda', 'Civic', 2006, 2012)])
    make_part('FROM', fits=[('Honda', 'Jazz', 2010, None)])
    make_part('UNTIL', fits=[('Honda', 'Fit', None, 2012)])

    assert numbers(parts_matching('Honda', 'Civic', 2006)) == ['RANGE']
    assert numbers(parts_matching('Honda', 'Civic', 2012)) == ['RANGE']
    assert numbers(parts_matching('Honda', 'Civic', 2005)) == []
    assert numbers(parts_matching('Honda', 'Civic', 2013)) == []
    assert numbers(parts_matching('Honda', 'Jazz', 2030)) == ['FROM']
    assert numbers(parts_matching('Honda', 'Jazz', 2009)) == []
    assert numbers(parts_matching('Honda', 'Fit', 1999)) == ['UNTIL']


def test_a_fitment_without_a_model_fits_every_model_of_the_make(make_part):
    make_part('WIDE', fits=[('Toyota', '', None, None)])

    assert numbers(parts_matching('Toyota', 'Anything', 2015)) == ['WIDE']
    assert numbers(parts_matching('Mazda', 'Anything', 2015)) == []


def test_universal_parts_match_every_vehicle(make_part):
    make_part('OIL', universal=True)
    make_part('SPECIFIC', fits=[('Toyota', 'Corolla', None, None)])

    assert numbers(parts_matching('Mazda', 'CX-5', 2016)) == ['OIL']
    assert numbers(parts_matching('Toyota', 'Corolla', 2016)) == ['OIL', 'SPECIFIC']


def test_without_a_make_every_active_part_is_returned_and_inactive_ones_are_not(make_part):
    make_part('ONE', universal=True)
    make_part('TWO', fits=[('Toyota', 'Corolla', None, None)])
    make_part('GONE', universal=True, is_active=False)

    assert numbers(parts_matching()) == ['ONE', 'TWO']


def test_a_part_with_two_matching_fitments_is_listed_once(make_part):
    make_part('DUP', fits=[('Toyota', 'Corolla', 2007, 2012), ('Toyota', 'Corolla', 2010, 2018)])
    assert numbers(parts_matching('Toyota', 'Corolla', 2011)) == ['DUP']


def test_fitment_descriptions_read_naturally(make_part):
    part = make_part('X', fits=[
        ('Toyota', 'Corolla', 2007, 2018), ('Toyota', 'Yaris', None, None), ('Mazda', '', None, None),
        ('Honda', 'Fit', 2010, None), ('Honda', 'Jazz', None, 2012),
    ])
    assert sorted(f.description for f in part.fitments.all()) == [
        'Honda Fit 2010 onwards', 'Honda Jazz up to 2012', 'Mazda (all models)',
        'Toyota Corolla 2007-2018', 'Toyota Yaris',
    ]


def test_stock_price_falls_back_to_the_guide_price(workshop, make_part, make_stock):
    part = make_part(price='20.00')
    default = make_stock(workshop, part)
    custom = make_stock(workshop, make_part('GL-T-0002', price='20.00'), unit_price=Decimal('24.50'))

    assert default.price == Decimal('20.00')
    assert custom.price == Decimal('24.50')


def test_stock_low_and_out_flags(workshop, make_part, make_stock):
    part = make_part()
    assert make_stock(workshop, part, quantity=0, reorder_level=2).is_out
    item = StockItem.objects.get()
    assert item.is_low
    item.quantity = 2
    assert item.is_low and not item.is_out
    item.quantity = 3
    assert not item.is_low


def test_a_part_can_only_be_stocked_once_per_workshop(workshop, other_workshop, make_part, make_stock):
    part = make_part()
    make_stock(workshop, part)
    make_stock(other_workshop, part)  # a different workshop is fine
    with pytest.raises(IntegrityError), transaction.atomic():
        make_stock(workshop, part)


# ---------------------------------------------------------------- the CSV format


@pytest.mark.parametrize('text, expected', [
    ('', []),
    ('Toyota|Corolla|2007-2018', [{'make': 'Toyota', 'model': 'Corolla', 'year_from': 2007, 'year_to': 2018}]),
    ('Toyota|*', [{'make': 'Toyota', 'model': '', 'year_from': None, 'year_to': None}]),
    ('Toyota', [{'make': 'Toyota', 'model': '', 'year_from': None, 'year_to': None}]),
    ('Toyota|Yaris|2010-', [{'make': 'Toyota', 'model': 'Yaris', 'year_from': 2010, 'year_to': None}]),
    ('Toyota|Yaris|-2012', [{'make': 'Toyota', 'model': 'Yaris', 'year_from': None, 'year_to': 2012}]),
    ('Toyota|Yaris|2015', [{'make': 'Toyota', 'model': 'Yaris', 'year_from': 2015, 'year_to': 2015}]),
    (' Mazda | * ; Honda|Fit|2007-2020 ;', [
        {'make': 'Mazda', 'model': '', 'year_from': None, 'year_to': None},
        {'make': 'Honda', 'model': 'Fit', 'year_from': 2007, 'year_to': 2020}]),
])
def test_parse_fitment(text, expected):
    assert parse_fitment(text) == expected


@pytest.mark.parametrize('text', ['|Corolla|2007', 'A|B|2007-2018|extra', 'Toyota|Corolla|abc', 'Toyota|Corolla|2018-2007',
                                  'Toyota|Corolla|1850-1900'])
def test_parse_fitment_rejects_malformed_entries(text):
    with pytest.raises(ValueError):
        parse_fitment(text)


def test_parse_years():
    assert parse_years('') == (None, None)
    assert parse_years('2010-2012') == (2010, 2012)


def test_import_creates_parts_and_fitments(tmp_path):
    path = write_csv(
        tmp_path,
        'T-1,Oil filter,Brand,filters,12.90,no,Toyota|Corolla|2007-2018;Toyota|Yaris,',
        'T-2,Wiper blade 400mm,,WIPERS,13.90,yes,,Fits most cars',
    )

    call_command('import_parts', str(path))

    part = Part.objects.get(part_number='T-1')
    assert (part.category, part.default_price, part.universal) == ('FILTERS', Decimal('12.90'), False)
    assert part.fitments.count() == 2
    assert Part.objects.get(part_number='T-2').universal
    assert Part.objects.get(part_number='T-2').description == 'Fits most cars'


def test_importing_twice_updates_instead_of_duplicating(tmp_path):
    path = write_csv(tmp_path, 'T-1,Oil filter,Brand,FILTERS,12.90,no,Toyota|Corolla|2007-2018')
    call_command('import_parts', str(path))

    path = write_csv(tmp_path, 'T-1,Oil filter (new),Brand,FILTERS,15.90,no,Mazda|Mazda3')
    call_command('import_parts', str(path))

    assert Part.objects.count() == 1
    part = Part.objects.get()
    assert (part.name, part.default_price) == ('Oil filter (new)', Decimal('15.90'))
    assert [(f.make, f.model) for f in part.fitments.all()] == [('Mazda', 'Mazda3')]  # old fitment replaced


@pytest.mark.parametrize('row, message', [
    ('T-1,Oil filter,,SPARKLES,12.90,no,Toyota|Corolla', 'category'),
    ('T-1,Oil filter,,FILTERS,cheap,no,Toyota|Corolla', 'default_price'),
    ('T-1,Oil filter,,FILTERS,-5,no,Toyota|Corolla', 'negative'),
    ('T-1,Oil filter,,FILTERS,12.90,maybe,Toyota|Corolla', 'universal'),
    ('T-1,Oil filter,,FILTERS,12.90,no,', 'needs a fitment'),
    ('T-1,Oil filter,,FILTERS,12.90,yes,Toyota|Corolla', 'universal part should not list'),
    (',Oil filter,,FILTERS,12.90,no,Toyota', 'part_number is empty'),
    ('T-1,,,FILTERS,12.90,no,Toyota', 'name is empty'),
    ('T-1,Oil filter,,FILTERS,12.90,no,Toyota|Corolla|2018-2007', 'backwards'),
])
def test_bad_rows_are_reported_with_their_line_number_and_nothing_is_imported(tmp_path, row, message):
    path = write_csv(tmp_path, 'GOOD-1,Fine part,,FILTERS,10.00,yes,,', row)

    with pytest.raises(CommandError) as error:
        call_command('import_parts', str(path))

    assert 'Line 3' in str(error.value) and message in str(error.value)
    assert not Part.objects.exists()  # the good row was not imported either


def test_duplicate_part_numbers_in_the_file_are_rejected(tmp_path):
    path = write_csv(tmp_path, 'T-1,One,,FILTERS,1,yes,,', 'T-1,Two,,FILTERS,2,yes,,')
    with pytest.raises(CommandError, match='more than once'):
        call_command('import_parts', str(path))


def test_missing_columns_and_missing_files_are_reported(tmp_path):
    path = tmp_path / 'bad.csv'
    path.write_text('part_number,name\nT-1,One\n', encoding='utf-8')
    with pytest.raises(CommandError, match='missing the column'):
        call_command('import_parts', str(path))
    with pytest.raises(CommandError, match='File not found'):
        call_command('import_parts', str(tmp_path / 'nope.csv'))


def test_a_csv_saved_by_excel_with_a_byte_order_mark_imports(tmp_path):
    path = tmp_path / 'excel.csv'
    path.write_bytes(('\ufeff' + CSV_HEADER + 'T-1,One,,FILTERS,1,yes,,\n').encode('utf-8'))
    call_command('import_parts', str(path))
    assert Part.objects.count() == 1


# ---------------------------------------------------------------- the demo catalogue


def test_the_demo_catalogue_has_200_valid_parts():
    call_command('import_parts', stdout=io.StringIO())

    assert Part.objects.count() == 200
    assert Part.objects.filter(universal=True).count() == 40
    assert PartFitment.objects.count() == 160
    assert not Part.objects.filter(universal=False, fitments__isnull=True).exists()
    assert set(Part.objects.values_list('category', flat=True)) == set(Part.Category.values)
    assert not Part.objects.filter(default_price__lte=0).exists()


def test_importing_the_demo_catalogue_twice_changes_nothing():
    call_command('import_parts', stdout=io.StringIO())
    call_command('import_parts', stdout=io.StringIO())
    assert (Part.objects.count(), PartFitment.objects.count()) == (200, 160)


def test_demo_catalogue_finds_parts_for_popular_nz_vehicles():
    call_command('import_parts', stdout=io.StringIO())

    corolla = parts_matching('Toyota', 'Corolla', 2012).filter(universal=False)
    assert [part.name for part in corolla.order_by('name')] == [
        'Air filter - Toyota Corolla 2007-2018', 'Front brake pads - Toyota Corolla 2007-2018',
        'Oil filter - Toyota Corolla 2007-2018', 'Spark plug set - Toyota Corolla 2007-2018',
    ]
    hilux = parts_matching('Toyota', 'Hilux', 2018).filter(universal=False)
    assert any(part.name.startswith('Fuel filter') for part in hilux)  # diesel: fuel filter, no spark plugs
    assert not any(part.name.startswith('Spark plug') for part in hilux)


def test_demo_csv_rows_are_all_well_formed():
    with open(DEFAULT_CSV, newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 200
    assert len({row['part_number'] for row in rows}) == 200
    assert all(row['brand'] == 'GarageLog Demo' for row in rows)


# ---------------------------------------------------------------- demo stock


def test_seed_demo_stock_loads_the_demo_library_first_when_it_is_empty(workshop):
    assert not Part.objects.exists()

    call_command('seed_demo_stock', stdout=io.StringIO())

    assert Part.objects.count() == 200
    assert StockItem.objects.filter(workshop=workshop).exists()


def test_seed_demo_stock_needs_a_workshop(db):
    with pytest.raises(CommandError, match='no workshops'):
        call_command('seed_demo_stock')


def test_seed_demo_stock_fills_every_workshop_and_is_repeatable(workshop, other_workshop):
    call_command('import_parts', stdout=io.StringIO())

    call_command('seed_demo_stock', stdout=io.StringIO())
    first = StockItem.objects.count()
    call_command('seed_demo_stock', stdout=io.StringIO())

    assert StockItem.objects.count() == first
    assert 250 < first < 350  # roughly three quarters of 200 parts, at each of two workshops
    assert StockItem.objects.filter(workshop=workshop).exists() and StockItem.objects.filter(workshop=other_workshop).exists()
    assert StockItem.objects.filter(quantity=0).exists() and StockItem.objects.filter(quantity__gt=5).exists()


def test_seed_demo_stock_does_not_overwrite_stock_that_was_changed(workshop):
    call_command('import_parts', stdout=io.StringIO())
    call_command('seed_demo_stock', stdout=io.StringIO())
    item = StockItem.objects.filter(workshop=workshop).first()
    item.quantity = 99
    item.save()

    call_command('seed_demo_stock', stdout=io.StringIO())

    item.refresh_from_db()
    assert item.quantity == 99


def test_seed_demo_stock_can_target_one_workshop(workshop, other_workshop):
    call_command('seed_demo_stock', '--workshop', 'North Workshop', stdout=io.StringIO())

    assert StockItem.objects.filter(workshop=other_workshop).exists()
    assert not StockItem.objects.filter(workshop=workshop).exists()


def test_seed_demo_stock_can_target_several_workshops_by_name(workshop, other_workshop, make_workshop):
    third = make_workshop('Third Workshop')

    call_command('seed_demo_stock', '--workshop', 'North Workshop', '--workshop', 'Third Workshop', stdout=io.StringIO())

    assert not StockItem.objects.filter(workshop=workshop).exists()
    assert StockItem.objects.filter(workshop=other_workshop).exists() and StockItem.objects.filter(workshop=third).exists()


def test_seed_demo_stock_rejects_an_unknown_workshop_name(workshop):
    with pytest.raises(CommandError, match='No workshop is named: Nowhere'):
        call_command('seed_demo_stock', '--workshop', 'Nowhere')
    assert not Part.objects.exists()  # it failed before loading anything


def test_seed_demo_stock_can_start_everything_at_zero(workshop):
    call_command('seed_demo_stock', '--empty', stdout=io.StringIO())

    assert StockItem.objects.filter(workshop=workshop).count() == 200
    assert not StockItem.objects.exclude(quantity=0).exists()


def test_a_workshop_added_later_can_be_seeded_without_touching_the_others(workshop, make_workshop):
    call_command('seed_demo_stock', stdout=io.StringIO())
    before = list(StockItem.objects.filter(workshop=workshop).values_list('pk', 'quantity'))
    newcomer = make_workshop('Brand New Workshop')

    call_command('seed_demo_stock', '--workshop', 'Brand New Workshop', stdout=io.StringIO())

    assert StockItem.objects.filter(workshop=newcomer).exists()
    assert list(StockItem.objects.filter(workshop=workshop).values_list('pk', 'quantity')) == before


# ---------------------------------------------------------------- seed_workshop_stock


def test_sample_seeding_adds_roughly_three_quarters_with_varied_quantities(workshop):
    call_command('import_parts', stdout=io.StringIO())

    added = seed_workshop_stock(workshop, SAMPLE)

    assert added == StockItem.objects.filter(workshop=workshop).count()
    assert 130 < added < 170
    quantities = set(StockItem.objects.values_list('quantity', flat=True))
    assert 0 in quantities and len(quantities) > 5


def test_empty_seeding_lists_every_active_part_at_zero(workshop, make_part):
    make_part('A', universal=True)
    make_part('B', universal=True)
    make_part('GONE', universal=True, is_active=False)

    added = seed_workshop_stock(workshop, EMPTY)

    assert added == 2
    assert sorted(StockItem.objects.values_list('part__part_number', flat=True)) == ['A', 'B']
    assert not StockItem.objects.exclude(quantity=0).exists()


def test_seeding_never_changes_stock_the_workshop_already_has(workshop, make_part, make_stock):
    kept = make_stock(workshop, make_part('KEEP', universal=True), quantity=42, bin_location='Z9')
    make_part('NEW', universal=True)

    added = seed_workshop_stock(workshop, EMPTY)

    kept.refresh_from_db()
    assert (kept.quantity, kept.bin_location) == (42, 'Z9')
    assert added == 1


def test_seeding_twice_adds_nothing_the_second_time(workshop):
    call_command('import_parts', stdout=io.StringIO())
    seed_workshop_stock(workshop, EMPTY)
    assert seed_workshop_stock(workshop, EMPTY) == 0
    assert seed_workshop_stock(workshop, SAMPLE) == 0


def test_sample_seeding_is_the_same_every_time(workshop, other_workshop):
    call_command('import_parts', stdout=io.StringIO())
    seed_workshop_stock(workshop)
    first = sorted(StockItem.objects.filter(workshop=workshop).values_list('part__part_number', 'quantity'))
    StockItem.objects.all().delete()

    seed_workshop_stock(workshop)

    assert sorted(StockItem.objects.filter(workshop=workshop).values_list('part__part_number', 'quantity')) == first
