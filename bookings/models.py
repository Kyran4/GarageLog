import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from inventory.models import StockItem

from . import scheduling


class Booking(models.Model):

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("QUOTED", "Quote received"),
        ("CONFIRMED", "Confirmed"),
        ("IN_PROGRESS", "In Progress"),
        ("CANCELLED", "Cancelled"),
        ("COMPLETED", "Completed"),
    ]

    # Bookings that still take up a slot.
    ACTIVE_STATUSES = ("PENDING", "QUOTED", "CONFIRMED")

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    workshop = models.ForeignKey(
        "workshops.Workshop",
        on_delete=models.PROTECT,
        related_name="bookings",
    )

    # Optional only so bookings made before vehicles existed still load; the forms require it.
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
    )

    mechanic = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_bookings",
    )

    booking_date = models.DateField()
    booking_time = models.TimeField()

    service_type = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    quote_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    quote_notes = models.TextField(blank=True)
    quoted_at = models.DateTimeField(null=True, blank=True)
    quote_accepted_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Safety net behind the checks in clean(): the database refuses a double booking
            # even if two requests arrive at the same moment.
            models.UniqueConstraint(
                fields=["vehicle", "booking_date", "booking_time"],
                condition=Q(status__in=["PENDING", "QUOTED", "CONFIRMED"]),
                name="unique_active_vehicle_slot",
                violation_error_message="This vehicle already has a booking at that time.",
            ),
            models.UniqueConstraint(
                fields=["mechanic", "booking_date", "booking_time"],
                condition=Q(status__in=["PENDING", "QUOTED", "CONFIRMED"]),
                name="unique_active_mechanic_slot",
                violation_error_message="That mechanic is already booked at that time.",
            ),
        ]

    def __str__(self):
        return f"Booking #{self.pk} - {self.service_type}"

    # ----------------------------------------------------------- validation

    def clean(self):
        super().clean()
        if (
            self.status not in self.ACTIVE_STATUSES
            or not (self.booking_date and self.booking_time)
            or not self.workshop_id
        ):
            return

        errors = {}
        if self.workshop.is_parts_warehouse:
            raise ValidationError({
                NON_FIELD_ERRORS: [
                    f"{self.workshop.name} is the parts warehouse and doesn't take bookings. "
                    f"Choose a workshop instead.",
                ],
            })
        if scheduling.booked_count(self.workshop, self.booking_date, self.booking_time, self.pk) \
                >= scheduling.capacity(self.workshop):
            errors["booking_time"] = "That time is fully booked. Please choose another time."

        if self.vehicle_id and self._clashes(vehicle_id=self.vehicle_id):
            errors["vehicle"] = "This vehicle already has a booking at that time."

        if self.mechanic_id:
            # Not tied to a field because the customer form has no mechanic field.
            problems = []
            if self.mechanic.workshop_id != self.workshop_id:
                problems.append("That mechanic works at a different workshop.")
            elif self._clashes(mechanic_id=self.mechanic_id):
                problems.append("That mechanic is already booked at that time.")
            if problems:
                errors[NON_FIELD_ERRORS] = problems

        if errors:
            raise ValidationError(errors)

    def _clashes(self, **match):
        return (
            Booking.objects.filter(
                booking_date=self.booking_date,
                booking_time=self.booking_time,
                status__in=self.ACTIVE_STATUSES,
                **match,
            )
            .exclude(pk=self.pk)
            .exists()
        )

    # ----------------------------------------------------------- helpers

    @property
    def starts_at(self):
        return scheduling.starts_at(self.booking_date, self.booking_time)

    @property
    def end_time(self):
        start = datetime.datetime.combine(self.booking_date, self.booking_time)
        return (start + datetime.timedelta(minutes=scheduling.SLOT_MINUTES)).time()

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_upcoming(self):
        return self.is_active and self.starts_at >= timezone.now()

    def _is_staff_here(self, user):
        """Admins work across workshops; a mechanic only at the workshop they are assigned to."""
        return user.is_admin_role or (user.is_mechanic and user.workshop_id == self.workshop_id)

    def can_be_edited_by(self, user):
        """Staff can edit bookings at their workshop. Customers can edit their own until it starts."""
        if self._is_staff_here(user):
            return True
        return (
            user.pk == self.customer_id
            and self.status != "QUOTED"
            and self.is_upcoming
        )

    def can_be_cancelled_by(self, user):
        if not self.is_active:
            return False
        if self._is_staff_here(user):
            return True
        return user.pk == self.customer_id and self.is_upcoming

    def can_be_quoted_by(self, user):
        if self.status != "PENDING" or not self.is_upcoming:
            return False
        if user.is_admin_role:
            return True
        return user.is_mechanic and user.workshop_id == self.workshop_id

    def can_accept_quote_by(self, user):
        return (
            user.pk == self.customer_id
            and self.status == "QUOTED"
            and self.quote_amount is not None
            and self.is_upcoming
        )


class BookingQuotePart(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="quote_parts",
    )
    stock_item = models.ForeignKey(
        StockItem,
        on_delete=models.PROTECT,
        related_name="booking_quote_parts",
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        ordering = ["pk"]

    def clean(self):
        super().clean()
        if self.booking_id and self.stock_item_id:
            if self.booking.workshop_id != self.stock_item.workshop_id:
                raise ValidationError({"stock_item": "Choose a part stocked at this booking's workshop."})

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class BookingQuoteLabour(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="quote_labour",
    )
    description = models.CharField(max_length=150)
    charge = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        ordering = ["pk"]

    @property
    def line_total(self):
        return self.charge


class ServiceLabourRecommendation(models.Model):
    service_type = models.CharField(max_length=100, unique=True)
    recommended_charge = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service_type"]
        verbose_name = "service labour recommendation"
        verbose_name_plural = "service labour recommendations"

    def __str__(self):
        return f"{self.service_type} - ${self.recommended_charge:.2f}"
