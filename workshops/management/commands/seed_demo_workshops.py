from django.core.management.base import BaseCommand

from workshops.models import Workshop


DEMO_WORKSHOPS = [
    ('Auckland Central Workshop', '1 Demo Street, Auckland', '09 000 0001'),
    ('North Shore Workshop', '2 Example Road, Takapuna, Auckland', '09 000 0002'),
]
DEMO_WAREHOUSE = ('Parts Warehouse', '3 Sample Avenue, Penrose, Auckland', '09 000 0003')


class Command(BaseCommand):
    help = (
        'Create the demo workshops and parts warehouse without creating demo user accounts. '
        'Existing locations are left unchanged.'
    )

    def handle(self, *args, **options):
        for name, address, phone in DEMO_WORKSHOPS:
            workshop, created = Workshop.objects.get_or_create(
                name=name,
                defaults={'address': address, 'phone': phone},
            )
            self.stdout.write(f"{'Created' if created else 'Found'} workshop '{workshop.name}'")

        warehouse = Workshop.get_warehouse()
        if warehouse is None:
            name, address, phone = DEMO_WAREHOUSE
            warehouse, created = Workshop.objects.get_or_create(
                name=name,
                defaults={
                    'address': address,
                    'phone': phone,
                    'is_parts_warehouse': True,
                },
            )
            if not created and not warehouse.is_parts_warehouse:
                warehouse.is_parts_warehouse = True
                warehouse.save(update_fields=['is_parts_warehouse'])
            self.stdout.write(
                f"{'Created' if created else 'Marked'} parts warehouse '{warehouse.name}'"
            )
        else:
            self.stdout.write(f"Found parts warehouse '{warehouse.name}'")

        self.stdout.write(self.style.SUCCESS('Demo locations are ready. No user accounts were created.'))
