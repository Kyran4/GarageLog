import random
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from inventory.models import Part, StockItem
from workshops.models import Workshop


class Command(BaseCommand):
    help = (
        'Give every workshop some demo stock from the parts catalogue (about three quarters of the parts, with '
        'varied quantities). Stock that already exists is left alone. Run import_parts first.'
    )

    def handle(self, *args, **options):
        parts = list(Part.objects.filter(is_active=True))
        workshops = list(Workshop.objects.all())
        if not parts:
            raise CommandError('There are no parts yet. Run "python manage.py import_parts" first.')
        if not workshops:
            raise CommandError('There are no workshops yet. Run "python manage.py seed_demo_users" first.')

        created = 0
        for workshop in workshops:
            for part in parts:
                # Seeded per workshop and part, so the demo data is the same every time.
                rng = random.Random(f'{workshop.pk}:{part.pk}')
                if rng.random() > 0.75:
                    continue  # this workshop does not stock this part
                price = None
                if rng.random() < 0.2:
                    price = (part.default_price * Decimal('1.10')).quantize(Decimal('0.10'))
                _, was_created = StockItem.objects.get_or_create(
                    workshop=workshop, part=part,
                    defaults={
                        'quantity': rng.choice([0, 2, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30]),
                        'reorder_level': rng.choice([2, 2, 3, 4]),
                        'unit_price': price,
                        'bin_location': f'{rng.choice("ABCD")}{rng.randint(1, 6)}-{rng.randint(1, 9)}',
                    },
                )
                created += was_created

        self.stdout.write(self.style.SUCCESS(
            f'Added {created} stock items across {len(workshops)} workshop(s). This is demo data.'
        ))
