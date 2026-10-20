from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

DEMO_PASSWORD = 'GarageLog-demo-1'

DEMO_USERS = [
    # username, role, first name, last name, is_admin
    ('admin', User.Role.ADMIN, 'Alex', 'Admin', True),
    ('mechanic1', User.Role.MECHANIC, 'Mia', 'Mechanic', False),
    ('mechanic2', User.Role.MECHANIC, 'Tane', 'Mechanic', False),
    ('customer1', User.Role.CUSTOMER, 'Casey', 'Customer', False),
    ('customer2', User.Role.CUSTOMER, 'Sam', 'Customer', False),
]


class Command(BaseCommand):
    help = 'Create (or reset) demo users for development: 1 admin, 2 mechanics, 2 customers.'

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

        for username, role, first_name, last_name, is_admin in DEMO_USERS:
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
            user.set_password(DEMO_PASSWORD)
            user.save()
            self.stdout.write(f"{'Created' if created else 'Reset'} {role.label.lower()} '{username}'")

        self.stdout.write(self.style.SUCCESS(f'Done. Every demo user has the password: {DEMO_PASSWORD}'))
