from decimal import Decimal

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import transaction
from django.db.models import F


class JobCard(models.Model):

    booking = models.OneToOneField(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="job_card"
    )

    mechanic = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_job_cards"
    )

    description = models.TextField(blank=True)

    work_done = models.TextField(blank=True)

    labor_charge = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Job Card #{self.id} - {self.booking.service_type}"

    @property
    def parts_total(self):
        return sum((item.line_total + item.freight_charge for item in self.parts.all()), Decimal("0.00"))

    @property
    def invoice_total(self):
        return self.labor_charge + self.parts_total


class JobPart(models.Model):
    """A part required for a job, with a customer price and private acquisition cost."""

    class Source(models.TextChoices):
        WORKSHOP = "WORKSHOP", "Workshop stock"
        WAREHOUSE = "WAREHOUSE", "Order from warehouse"
        CATALOGUE = "CATALOGUE", "Order from catalogue"
        MANUAL = "MANUAL", "Manual part"

    class SupplyStatus(models.TextChoices):
        READY = "READY", "Ready"
        BACKORDERED = "BACKORDERED", "Backordered"
        ON_ORDER = "ON_ORDER", "On supplier order"

    job_card = models.ForeignKey(JobCard, on_delete=models.CASCADE, related_name="parts")
    stock_item = models.ForeignKey(
        "inventory.StockItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_reservations",
    )
    part = models.ForeignKey(
        "inventory.Part",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="job_assignments",
    )
    name = models.CharField(max_length=150)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WORKSHOP)
    supply_status = models.CharField(
        max_length=20,
        choices=SupplyStatus.choices,
        default=SupplyStatus.READY,
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)], default=1)
    unit_cost = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Internal acquisition cost; never shown on the customer invoice.",
    )
    unit_price = models.DecimalField(
        "customer unit price",
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    freight_charge = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Customer-facing freight charge for warehouse or catalogue orders.",
    )

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return f"{self.name} for job card #{self.job_card_id}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def freight_description(self):
        return f"{self.get_source_display()} freight"

    def delete(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db
        with transaction.atomic(using=using):
            current = (
                type(self).objects.using(using)
                .select_for_update()
                .filter(pk=self.pk)
                .first()
            )
            if current is None:
                return (0, {})
            if current.stock_item_id:
                from inventory.models import StockItem

                StockItem.objects.using(using).filter(pk=current.stock_item_id).update(
                    quantity=F("quantity") + current.quantity
                )
            return super(JobPart, current).delete(*args, **kwargs)


class SupplierOrder(models.Model):
    """A warehouse supplier order for general stock or a job-card backorder."""

    job_part = models.OneToOneField(
        JobPart,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_order",
    )
    part = models.ForeignKey(
        "inventory.Part",
        on_delete=models.PROTECT,
        related_name="supplier_orders",
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)], default=1)
    supplier = models.CharField(max_length=150)
    supplier_reference = models.CharField(max_length=100, blank=True)
    unit_cost = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    ordered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="supplier_orders_placed",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_orders_received",
    )
    ordered_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-ordered_at"]

    def __str__(self):
        return f"Supplier order for {self.part.name} ({self.quantity})"
