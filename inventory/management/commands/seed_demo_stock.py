from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Part
from inventory.seeding import EMPTY, SAMPLE, seed_workshop_stock
from workshops.models import Workshop


class Command(BaseCommand):
    help = (
        'Give workshops a starting set of stock from the parts library. If the library is empty it loads the '
        '200-part demo catalogue first, so this one command is all you need. Stock a workshop already has is left '
        'alone, so it is safe to run again, for example after adding a new workshop.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--workshop', action='append', metavar='NAME',
            help='Only seed this workshop (by name). Repeat for more than one. Default: every workshop.',
        )
        parser.add_argument(
            '--empty', action='store_true',
            help='List every part at a quantity of 0 instead of sample quantities.',
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

        mode = EMPTY if options['empty'] else SAMPLE
        for workshop in workshops:
            added = seed_workshop_stock(workshop, mode)
            self.stdout.write(f'{workshop.name}: added {added} part(s) to stock.')
        self.stdout.write(self.style.SUCCESS(
            'Done. This is '
            + ('every library part at quantity 0.' if mode == EMPTY else 'demo data with sample quantities.')
        ))
