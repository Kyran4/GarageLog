from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from vehicles.models import Vehicle
from workshops.models import Workshop

DEMO_PASSWORD = 'GarageLog-demo-1'

DEMO_WORKSHOPS = [
    # name, address, phone
    ('Auckland Central Workshop', '1 Demo Street, Auckland', '09 000 0001'),
    ('North Shore Workshop', '2 Example Road, Takapuna, Auckland', '09 000 0002'),
]

DEMO_WAREHOUSE = ('Parts Warehouse', '3 Sample Avenue, Penrose, Auckland', '09 000 0003')

DEMO_USERS = [
    # username, role, first name, last name, is_admin, workshop name
    ('admin', User.Role.ADMIN, 'Alex', 'Admin', True, None),
    ('mechanic1', User.Role.MECHANIC, 'Mia', 'Mechanic', False, 'Auckland Central Workshop'),
    ('mechanic2', User.Role.MECHANIC, 'Tane', 'Mechanic', False, 'North Shore Workshop'),
    ('warehouse1', User.Role.MECHANIC, 'Wiremu', 'Warehouse', False, DEMO_WAREHOUSE[0]),
    ('customer1', User.Role.CUSTOMER, 'Casey', 'Customer', False, None),
    ('customer2', User.Role.CUSTOMER, 'Sam', 'Customer', False, None),
]

DEMO_VEHICLES = [
    # owner username, plate, make, model, year
    ('customer1', 'DEMO01', 'Toyota', 'Corolla', 2012),
    ('customer2', 'DEMO02', 'Mazda', 'CX-5', 2016),
]


class Command(BaseCommand):
    help = (
        'Create (or reset) demo data for development: 2 workshops and the parts warehouse, 1 admin, 2 mechanics (one per '
        'workshop), 1 warehouse staff member, 2 customers and a vehicle for each customer.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Run even when DEBUG is off. Never do this on a real deployment.',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError(
                'Refusing to create demo users with known passwords while DEBUG is off. '
                'Use --force only on a throwaway database.'
            )

        workshops = {}
        for name, address, phone in DEMO_WORKSHOPS:
            workshop, created = Workshop.objects.get_or_create(
                name=name, defaults={'address': address, 'phone': phone},
            )
            workshops[name] = workshop
            self.stdout.write(f"{'Created' if created else 'Found'} workshop '{name}'")

        # The parts warehouse. If this database already has one (under any name), use that one.
        warehouse = Workshop.get_warehouse()
        if warehouse is None:
            name, address, phone = DEMO_WAREHOUSE
            warehouse, created = Workshop.objects.get_or_create(
                name=name, defaults={'address': address, 'phone': phone},
            )
            warehouse.is_parts_warehouse = True
            warehouse.save()
            self.stdout.write(f"{'Created' if created else 'Marked'} parts warehouse '{name}'")
        else:
            self.stdout.write(f"Found parts warehouse '{warehouse.name}'")
        workshops[DEMO_WAREHOUSE[0]] = warehouse

        users = {}
        for username, role, first_name, last_name, is_admin, workshop_name in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@example.com'},
            )
            user.role = role
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.email_verified = True
            user.is_staff = is_admin
            user.is_superuser = is_admin
            user.workshop = workshops[workshop_name] if workshop_name else None
            user.set_password(DEMO_PASSWORD)
            user.save()
            users[username] = user
            self.stdout.write(f"{'Created' if created else 'Reset'} {role.label.lower()} '{username}'")

        for owner, plate, make, model, year in DEMO_VEHICLES:
            vehicle, created = Vehicle.objects.get_or_create(
                plate=plate,
                defaults={'owner': users[owner], 'make': make, 'model': model, 'year': year},
            )
            self.stdout.write(f"{'Created' if created else 'Found'} vehicle {vehicle.plate}")

        self.stdout.write(self.style.SUCCESS(f'Done. Every demo user has the password: {DEMO_PASSWORD}'))
