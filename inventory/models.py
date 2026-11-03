from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class Part(models.Model):
    """A part in the shared catalogue. How many each workshop holds, and at what price, is a StockItem."""

    class Category(models.TextChoices):
        FLUIDS = 'FLUIDS', 'Oils and fluids'
        FILTERS = 'FILTERS', 'Filters'
        BRAKES = 'BRAKES', 'Brakes'
        IGNITION = 'IGNITION', 'Ignition'
        ELECTRICAL = 'ELECTRICAL', 'Electrical and bulbs'
        WIPERS = 'WIPERS', 'Wipers'
        WORKSHOP = 'WORKSHOP', 'Workshop supplies'

    part_number = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    brand = models.CharField(max_length=60, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.TextField(blank=True)
    default_price = models.DecimalField(
        'guide price', max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal('0'))],
        help_text='Guide price in NZD. A workshop can set its own price on its stock.',
    )
    universal = models.BooleanField(
        default=False,
        help_text='Fits any vehicle (for example oil, wiper blades and bulbs), so it has no fitment list.',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.part_number} - {self.name}'


class PartFitment(models.Model):
    """One make (and optionally model and years) that a part fits."""

    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='fitments')
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=50, blank=True, help_text='Leave blank to fit every model of this make.')
    year_from = models.PositiveSmallIntegerField(null=True, blank=True)
    year_to = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['make', 'model', 'year_from']
        constraints = [
            models.UniqueConstraint(
                fields=['part', 'make', 'model', 'year_from', 'year_to'], name='unique_part_fitment',
            ),
        ]

    def __str__(self):
        return f'{self.part.part_number}: {self.description}'

    @property
    def description(self):
        text = f'{self.make} {self.model}'.strip() if self.model else f'{self.make} (all models)'
        if self.year_from and self.year_to:
            return f'{text} {self.year_from}-{self.year_to}'
        if self.year_from:
            return f'{text} {self.year_from} onwards'
        if self.year_to:
            return f'{text} up to {self.year_to}'
        return text


def parts_matching(make='', model='', year=None, parts=None):
    """Active parts that fit a vehicle: universal parts plus parts whose fitment matches.

    Make and model match ignoring case. A fitment with no model fits every model of its make,
    and a fitment's year range is only checked when a year is given.
    """
    parts = Part.objects.filter(is_active=True) if parts is None else parts
    make, model = (make or '').strip(), (model or '').strip()
    if not make:
        return parts

    fits = Q(fitments__make__iexact=make)
    if model:
        fits &= Q(fitments__model__iexact=model) | Q(fitments__model='')
    if year:
        fits &= (Q(fitments__year_from__isnull=True) | Q(fitments__year_from__lte=year)) & (
            Q(fitments__year_to__isnull=True) | Q(fitments__year_to__gte=year)
        )
    return parts.filter(Q(universal=True) | fits).distinct()


class StockItem(models.Model):
    """How many of a part one workshop holds, and its price there."""

    workshop = models.ForeignKey('workshops.Workshop', on_delete=models.CASCADE, related_name='stock')
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='stock_items')
    quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(
        default=2, help_text='Flag this part as low when the quantity is at or below this number.',
    )
    unit_price = models.DecimalField(
        'workshop price', max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text="Leave blank to use the part's guide price.",
    )
    unit_cost = models.DecimalField(
        'last supplier unit cost', max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Internal supplier cost from the most recent warehouse order.',
    )
    bin_location = models.CharField(max_length=30, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['part__category', 'part__name']
        constraints = [
            models.UniqueConstraint(fields=['workshop', 'part'], name='unique_stock_per_workshop_part'),
        ]

    def __str__(self):
        return f'{self.part.part_number} at {self.workshop.name} ({self.quantity})'

    @property
    def price(self):
        return self.part.default_price if self.unit_price is None else self.unit_price

    @property
    def is_out(self):
        return self.quantity == 0

    @property
    def is_low(self):
        return self.quantity <= self.reorder_level
