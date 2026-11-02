from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Part
from inventory.seeding import EMPTY, WAREHOUSE, default_mode, seed_workshop_stock
from workshops.models import Workshop


class Command(BaseCommand):
    help = (
        'Give workshops a starting set of stock from the parts library. Workshops get sample quantities of most '
        'parts, and the parts warehouse gets every part in large quantities. If the library is empty it loads the '
        '200-part demo catalogue first, so this one command is all you need. Stock a location already has is left '
        'alone, so it is safe to run again, for example after adding a new workshop.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--workshop', action='append', metavar='NAME',
            help='Only seed this workshop (by name). Repeat for more than one. Default: every workshop.',
        )
        parser.add_argument(
            '--empty', action='store_true',
            help='List every part at a quantity of 0 instead of sample or warehouse quantities.',
        )

    def handle(self, *args, **options):
        workshops = Workshop.objects.order_by('name')
        if options['workshop']:
            workshops = workshops.filter(name__in=options['workshop'])
            missing = set(options['workshop']) - set(workshops.values_list('name', flat=True))
            if missing:
                raise CommandError(f'No workshop is named: {", ".join(sorted(missing))}')
        workshops = list(workshops)
        if not workshops:
            raise CommandError('There are no workshops yet. Run "python manage.py seed_demo_users" first.')

        if not Part.objects.exists():
            self.stdout.write('The parts library is empty, so the demo catalogue is being loaded first.')
            call_command('import_parts', stdout=self.stdout)

        for workshop in workshops:
            mode = EMPTY if options['empty'] else default_mode(workshop)
            added = seed_workshop_stock(workshop, mode)
            kind = {
                EMPTY: 'at quantity 0',
                WAREHOUSE: 'warehouse quantities',
            }.get(mode, 'sample quantities')
            label = f'{workshop.name} (parts warehouse)' if workshop.is_parts_warehouse else workshop.name
            self.stdout.write(f'{label}: added {added} part(s) to stock, {kind}.')
        self.stdout.write(self.style.SUCCESS('Done. This is demo data.'))
