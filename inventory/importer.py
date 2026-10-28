"""Reading a parts CSV into the catalogue.

CSV columns: part_number, name, brand, category, default_price, universal, fitment, description.

The fitment column lists what a part fits, separated by semicolons. Each entry is
Make|Model|Years, where Model can be * (or empty) for every model of that make, and Years is
optional: 2007-2018, 2010- (from 2010), -2012 (up to 2012) or a single year.

    Toyota|Corolla|2007-2018;Toyota|Yaris;Mazda|*
"""
import csv
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Part, PartFitment

REQUIRED_COLUMNS = ['part_number', 'name', 'category', 'default_price']
TRUE_WORDS = {'yes', 'y', 'true', '1'}
FALSE_WORDS = {'no', 'n', 'false', '0', ''}


def _parse_year(text):
    year = int(text)
    if not 1900 <= year <= 2100:
        raise ValueError(f'the year {year} is not between 1900 and 2100')
    return year


def parse_years(text):
    text = text.strip()
    if not text:
        return None, None
    if '-' not in text:
        year = _parse_year(text)
        return year, year
    start, _, end = text.partition('-')
    year_from = _parse_year(start) if start.strip() else None
    year_to = _parse_year(end) if end.strip() else None
    if year_from and year_to and year_from > year_to:
        raise ValueError(f'the years {text} run backwards')
    return year_from, year_to


def parse_fitment(text):
    """Turn a fitment cell into a list of dicts for PartFitment. Raises ValueError if it is malformed."""
    fitments = []
    for entry in (text or '').split(';'):
        entry = entry.strip()
        if not entry:
            continue
        pieces = [piece.strip() for piece in entry.split('|')]
        if len(pieces) > 3 or not pieces[0]:
            raise ValueError(f'"{entry}" should look like Make|Model|Years')
        model = pieces[1] if len(pieces) > 1 else ''
        years = pieces[2] if len(pieces) > 2 else ''
        year_from, year_to = parse_years(years)
        fitments.append({
            'make': pieces[0],
            'model': '' if model == '*' else model,
            'year_from': year_from,
            'year_to': year_to,
        })
    return fitments


def parse_row(row):
    """Validate one CSV row and return the cleaned values. Raises ValueError with a readable message."""
    part_number = (row.get('part_number') or '').strip()
    name = (row.get('name') or '').strip()
    if not part_number:
        raise ValueError('part_number is empty')
    if not name:
        raise ValueError('name is empty')

    category = (row.get('category') or '').strip().upper()
    if category not in Part.Category.values:
        raise ValueError(f'category "{row.get("category")}" is not one of {", ".join(Part.Category.values)}')

    try:
        price = Decimal((row.get('default_price') or '').strip())
    except InvalidOperation:
        raise ValueError(f'default_price "{row.get("default_price")}" is not a number') from None
    if price < 0:
        raise ValueError('default_price cannot be negative')

    universal_text = (row.get('universal') or '').strip().lower()
    if universal_text not in TRUE_WORDS | FALSE_WORDS:
        raise ValueError(f'universal "{row.get("universal")}" should be yes or no')
    universal = universal_text in TRUE_WORDS

    fitments = parse_fitment(row.get('fitment'))
    if universal and fitments:
        raise ValueError('a universal part should not list a fitment')
    if not universal and not fitments:
        raise ValueError('a part that is not universal needs a fitment')

    return {
        'part_number': part_number,
        'fields': {
            'name': name,
            'brand': (row.get('brand') or '').strip(),
            'category': category,
            'default_price': price,
            'universal': universal,
            'description': (row.get('description') or '').strip(),
        },
        'fitments': fitments,
    }


def read_rows(path):
    """Return (parsed rows, errors) for a CSV file. Errors are strings that include the line number."""
    with open(path, newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            return [], [f'The CSV is missing the column(s): {", ".join(missing)}']

        parsed, errors, seen = [], [], set()
        for line_number, row in enumerate(reader, start=2):  # line 1 is the header
            try:
                cleaned = parse_row(row)
            except ValueError as error:
                errors.append(f'Line {line_number}: {error}')
                continue
            if cleaned['part_number'] in seen:
                errors.append(f'Line {line_number}: part_number {cleaned["part_number"]} appears more than once')
                continue
            seen.add(cleaned['part_number'])
            parsed.append(cleaned)
    return parsed, errors


def import_parts(parsed):
    """Create or update parts and replace their fitments. Returns (created, updated)."""
    created = updated = 0
    with transaction.atomic():
        for item in parsed:
            part, was_created = Part.objects.update_or_create(
                part_number=item['part_number'], defaults=item['fields'],
            )
            created += was_created
            updated += not was_created
            part.fitments.all().delete()
            PartFitment.objects.bulk_create([PartFitment(part=part, **fitment) for fitment in item['fitments']])
    return created, updated
