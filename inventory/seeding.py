"""Giving a workshop a starting set of stock from the shared parts library."""
import random
from decimal import Decimal

from .models import Part, StockItem

SAMPLE = 'sample'        # varied quantities for about three quarters of the parts, so a demo looks lived in
EMPTY = 'empty'          # every part listed with a quantity of 0, ready for the real counts to be entered
WAREHOUSE = 'warehouse'  # every part, in the larger quantities a central store holds


def default_mode(workshop):
    return WAREHOUSE if workshop.is_parts_warehouse else SAMPLE


def seed_workshop_stock(workshop, mode=None):
    """Add the active library parts this workshop doesn't stock yet. Returns how many were added.

    With no mode given, the parts warehouse gets every part in large quantities and a workshop
    gets sample quantities for most parts.

    Parts the workshop already stocks are never touched, so this is safe to run again. Sample
    quantities come from a generator seeded per workshop and part, so the demo data is the same
    every time.
    """
    mode = mode or default_mode(workshop)
    already = StockItem.objects.filter(workshop=workshop).values_list('part_id', flat=True)
    missing = Part.objects.filter(is_active=True).exclude(pk__in=already)

    items = []
    for part in missing:
        if mode == EMPTY:
            items.append(StockItem(workshop=workshop, part=part, quantity=0))
            continue
        rng = random.Random(f'{workshop.pk}:{part.pk}')
        if mode == WAREHOUSE:
            items.append(StockItem(
                workshop=workshop, part=part,
                quantity=rng.choice([20, 30, 40, 50, 60, 80, 100, 120, 150]),
                reorder_level=rng.choice([10, 15, 20]),
                bin_location=f'W-{rng.choice("ABCDEF")}{rng.randint(1, 9)}-{rng.randint(1, 9)}',
            ))
            continue
        if rng.random() > 0.75:
            continue  # this workshop does not stock this part
        price = None
        if rng.random() < 0.2:
            price = (part.default_price * Decimal('1.10')).quantize(Decimal('0.10'))
        items.append(StockItem(
            workshop=workshop, part=part,
            quantity=rng.choice([0, 2, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30]),
            reorder_level=rng.choice([2, 2, 3, 4]),
            unit_price=price,
            bin_location=f'{rng.choice("ABCD")}{rng.randint(1, 6)}-{rng.randint(1, 9)}',
        ))
    StockItem.objects.bulk_create(items, ignore_conflicts=True)
    return len(items)
