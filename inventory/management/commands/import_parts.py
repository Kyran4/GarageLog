from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inventory.importer import import_parts, read_rows

DEFAULT_CSV = Path(__file__).resolve().parents[2] / 'data' / 'demo_parts.csv'


class Command(BaseCommand):
    help = (
        'Import parts from a CSV file into the shared catalogue. Parts are matched on part_number, so running '
        'it again updates existing parts instead of duplicating them. Uses the 200-part demo catalogue by default.'
    )

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=str(DEFAULT_CSV), help='CSV file to import.')

    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.is_file():
            raise CommandError(f'File not found: {path}')

        parsed, errors = read_rows(path)
        if errors:
            shown = '\n'.join(errors[:10])
            more = f'\n...and {len(errors) - 10} more' if len(errors) > 10 else ''
            raise CommandError(f'Nothing was imported because the CSV has problems:\n{shown}{more}')

        created, updated = import_parts(parsed)
        self.stdout.write(self.style.SUCCESS(f'Imported {len(parsed)} parts ({created} new, {updated} updated).'))
