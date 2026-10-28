import datetime
from decimal import Decimal

import pytest

from accounts.models import User
from bookings import scheduling
from bookings.models import Booking
from inventory.models import Part, PartFitment, StockItem
from vehicles.models import Vehicle
from workshops.models import Workshop

PASSWORD = 'S3cure-Pass-Word!'


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """Real hashers are deliberately slow; use a fast one so the test suite stays quick."""
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


def default_workshop():
    """The workshop most tests use. Created on first use."""
    return Workshop.objects.get_or_create(name='Central Workshop')[0]


@pytest.fixture
def make_workshop(db):
    def _make(name='Test Workshop', **extra):
        return Workshop.objects.create(name=name, **extra)

    return _make


@pytest.fixture
def workshop(db):
    return default_workshop()


@pytest.fixture
def other_workshop(make_workshop):
    return make_workshop('North Workshop')


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def make_user(db):
    """Create a verified, active user. Override any field with keyword arguments."""

    def _make(username, role=User.Role.CUSTOMER, **extra):
        fields = {
            'email': f'{username}@example.com',
            'password': PASSWORD,
            'role': role,
            'is_active': True,
            'email_verified': True,
        }
        fields.update(extra)
        if role == User.Role.MECHANIC and 'workshop' not in fields:
            fields['workshop'] = default_workshop()
        return User.objects.create_user(username=username, **fields)

    return _make


@pytest.fixture
def customer(make_user):
    return make_user('customer', User.Role.CUSTOMER, first_name='Casey')


@pytest.fixture
def mechanic(make_user):
    return make_user('mechanic', User.Role.MECHANIC)


@pytest.fixture
def admin_user(make_user):
    return make_user('adminuser', User.Role.ADMIN)


@pytest.fixture
def make_vehicle(db):
    def _make(owner, plate='ABC123', **extra):
        fields = {'make': 'Toyota', 'model': 'Corolla', 'year': 2015}
        fields.update(extra)
        return Vehicle.objects.create(owner=owner, plate=plate, **fields)

    return _make


@pytest.fixture
def vehicle(customer, make_vehicle):
    return make_vehicle(customer)


@pytest.fixture
def open_day():
    """A weekday at least a day from now, so bookings on it are valid."""
    return scheduling.next_open_date()


@pytest.fixture
def make_booking(db, open_day):
    def _make(customer, vehicle=None, date=None, time=datetime.time(10, 0), status='PENDING', mechanic=None,
              workshop=None, **extra):
        fields = {'service_type': 'Oil Change'}
        fields.update(extra)
        return Booking.objects.create(
            customer=customer, vehicle=vehicle, booking_date=date or open_day,
            booking_time=time, status=status, mechanic=mechanic,
            workshop=workshop or default_workshop(), **fields,
        )

    return _make


@pytest.fixture
def booking_data(open_day):
    """POST data for a valid booking form; override any field with keyword arguments."""

    def _data(vehicle, **overrides):
        data = {
            'workshop': default_workshop().pk,
            'vehicle': vehicle.pk,
            'booking_date': open_day.isoformat(),
            'booking_time': '10:00',
            'service_type': 'Oil Change',
            'notes': '',
        }
        data.update(overrides)
        return data

    return _data


@pytest.fixture
def make_part(db):
    """Create a catalogue part. `fits` is a list of (make, model, year_from, year_to) tuples."""

    def _make(part_number='GL-T-0001', name='Test part', category='FILTERS', price='10.00', universal=False,
              fits=(), **extra):
        part = Part.objects.create(
            part_number=part_number, name=name, category=category, default_price=Decimal(str(price)),
            universal=universal, **extra,
        )
        for make, model, year_from, year_to in fits:
            PartFitment.objects.create(part=part, make=make, model=model, year_from=year_from, year_to=year_to)
        return part

    return _make


@pytest.fixture
def make_stock(db):
    def _make(workshop, part, quantity=5, **extra):
        return StockItem.objects.create(workshop=workshop, part=part, quantity=quantity, **extra)

    return _make
