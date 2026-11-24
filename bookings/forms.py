import datetime

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.models import User
from inventory.models import StockItem, parts_matching
from vehicles.models import Vehicle
from workshops.models import Workshop

from . import scheduling
from .models import Booking


def _parse_time(value):
    return datetime.datetime.strptime(value, "%H:%M").time()


class TaggedSelect(forms.Select):
    """A select whose options carry an extra data attribute (for example data-owner), so the
    page can show only the options that belong to whatever is selected in another field."""

    def __init__(self, *args, tag_name, tag_getter, **kwargs):
        super().__init__(*args, **kwargs)
        self.tag_name = tag_name
        self.tag_getter = tag_getter

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"][self.tag_name] = self.tag_getter(instance)
        return option


class WorkshopChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} ({obj.hours_text})"


class VehicleChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, show_owner=False, **kwargs):
        self.show_owner = show_owner
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        label = str(obj)
        return f"{label} ({obj.owner.username})" if self.show_owner else label


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} ({obj.username})"


class BookingForm(BootstrapFormMixin, forms.ModelForm):
    """The form customers use to book (and edit) a service."""

    SERVICE_CHOICES = [
        ("", "Select a service"),
        ("WoF Inspection", "WoF Inspection"),
        ("Oil Change", "Oil Change"),
        ("Full Service", "Full Service"),
        ("Brake Repair", "Brake Repair"),
        ("Tyre Replacement", "Tyre Replacement"),
        ("Battery Replacement", "Battery Replacement"),
        ("Engine Diagnostics", "Engine Diagnostics"),
        ("Other", "Other (please specify)"),
    ]

    # Customers can only book their own vehicles; the staff form turns this off.
    own_vehicles_only = True

    workshop = WorkshopChoiceField(
        queryset=Workshop.objects.bookable(),
        empty_label="Select a workshop",
    )

    vehicle = VehicleChoiceField(
        queryset=Vehicle.objects.none(),
        empty_label="Select a vehicle",
    )

    booking_time = forms.TypedChoiceField(
        label="Time",
        choices=[("", "Select a time")],
        coerce=_parse_time,
        empty_value=None,
        help_text=f"Each booking is {scheduling.SLOT_MINUTES} minutes. The workshop's opening hours are shown "
                  f"next to its name.",
    )

    earlier_slot_opt_in = forms.BooleanField(
        label="Notify me if an earlier time becomes available",
        required=False,
        help_text="If someone cancels an earlier booking at this workshop on the same day, "
                  "we'll offer you that time.",
    )

    same_issue_returned = forms.BooleanField(
        label="Same issue has returned",
        required=False,
        help_text="Link this booking to the previous repair so the mechanic can review what was tried.",
    )
    courtesy_vehicle_requested = forms.BooleanField(
        label="Request a courtesy vehicle",
        required=False,
    )
    courtesy_vehicle_start = forms.DateField(
        label="Courtesy vehicle from",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    courtesy_vehicle_end = forms.DateField(
        label="Courtesy vehicle until",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    service_type = forms.ChoiceField(
        choices=SERVICE_CHOICES
    )

    other_service = forms.CharField(
        required=False,
        max_length=100,
        label="Other service",
        widget=forms.TextInput(
            attrs={"placeholder": "Describe the service"}
        )
    )

    class Meta:
        model = Booking

        fields = [
            "workshop",
            "vehicle",
            "booking_date",
            "booking_time",
            "earlier_slot_opt_in",
            "service_type",
            "notes",
            "same_issue_returned",
            "courtesy_vehicle_requested",
            "courtesy_vehicle_start",
            "courtesy_vehicle_end",
        ]

        widgets = {
            "booking_date": forms.DateInput(
                attrs={"type": "date"}
            ),
            "booking_time": forms.Select(
                choices=[
                (
                    f"{hour:02d}:{minute:02d}",
                    f"{(hour % 12) or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
                )
                for hour in range(8, 18)
                for minute in (0, 30)
                ]
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        booking = self.instance

        self.fields["booking_date"].widget.attrs["min"] = timezone.localdate().isoformat()
        if user is not None and self.own_vehicles_only:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(owner=user)

        # The parts warehouse never takes bookings. A workshop that has since been deactivated (or turned
        # into the warehouse) stays valid for bookings already made there, so they can still be edited.
        workshops = Workshop.objects.filter(Q(is_active=True, is_parts_warehouse=False) | Q(pk=booking.workshop_id))
        self.fields["workshop"].queryset = workshops
        self.fields["booking_time"].choices = [("", "Select a time")] + scheduling.all_slot_choices(workshops)

        if booking.pk:
            # Editing: show the saved time in the dropdown, and show a custom service as "Other".
            self.initial["booking_time"] = booking.booking_time.strftime("%H:%M")
            known = {value for value, _ in self.SERVICE_CHOICES if value}
            if booking.service_type not in known:
                self.initial["service_type"] = "Other"
                self.initial["other_service"] = booking.service_type
            # Moving a booking to another workshop means making a new booking there.
            self.fields["workshop"].disabled = True
            self.fields["workshop"].help_text = "To use a different workshop, cancel this booking and make a new one."
        elif workshops.count() == 1:
            self.initial.setdefault("workshop", workshops.first().pk)

        # "Same issue has returned" only means something when there is a previous repair to link to.
        if not booking.previous_booking_id and not self.initial.get("same_issue_returned"):
            del self.fields["same_issue_returned"]

    # ----------------------------------------------------------- helpers

    def _workshop(self):
        workshop = self.cleaned_data.get("workshop")
        if workshop is None and self.instance.workshop_id:
            workshop = self.instance.workshop
        return workshop

    def _schedule_changed(self):
        changed = {"booking_date", "booking_time", "workshop"} & set(self.changed_data)
        return self.instance.pk is None or bool(changed)

    # ----------------------------------------------------------- validation

    def clean_booking_date(self):
        date = self.cleaned_data["booking_date"]

        if self.instance.pk and date == self.instance.booking_date:
            return date  # an unchanged date on an existing booking is fine, even if it is now past

        if date < timezone.localdate():
            raise forms.ValidationError(
                "You cannot book a date in the past."
            )

        return date

    def clean(self):
        cleaned_data = super().clean()

        requested = cleaned_data.get("courtesy_vehicle_requested")
        start = cleaned_data.get("courtesy_vehicle_start")
        end = cleaned_data.get("courtesy_vehicle_end")
        if requested:
            if not start:
                self.add_error("courtesy_vehicle_start", "Enter the date you need the courtesy vehicle.")
            if not end:
                self.add_error("courtesy_vehicle_end", "Enter the date you will return the courtesy vehicle.")
            if start and end and end < start:
                self.add_error("courtesy_vehicle_end", "The return date cannot be before the collection date.")

        service = cleaned_data.get("service_type")
        other = (cleaned_data.get("other_service") or "").strip()

        if service == "Other":
            if not other:
                self.add_error(
                    "other_service",
                    "Please describe the service you need."
                )
            else:
                cleaned_data["service_type"] = other

        workshop = self._workshop()
        date = cleaned_data.get("booking_date")
        time = cleaned_data.get("booking_time")
        if workshop and date and time and self._schedule_changed():
            closed = scheduling.closed_reason(workshop, date)
            if closed:
                self.add_error("booking_date", closed)
            elif time not in workshop.slot_starts():
                self.add_error(
                    "booking_time",
                    f"That time is outside {workshop.name}'s hours ({workshop.hours_text}). "
                    f"Please choose another time.",
                )
            elif scheduling.starts_at(date, time) < timezone.now():
                self.add_error("booking_time", "That time has already passed. Please choose a later time.")

        return cleaned_data

    def validate_constraints(self):
        # Clashes are checked in Booking.clean() with friendlier messages. The database
        # constraints stay in place as a safety net.
        pass


class StaffBookingForm(BookingForm):
    """For admins and mechanics: book on behalf of a customer, assign a mechanic, set the status.

    Admins choose any workshop. A mechanic's bookings are always at their own workshop, so the
    workshop field is not shown to them.
    """

    own_vehicles_only = False

    customer = UserChoiceField(
        queryset=User.objects.filter(role=User.Role.CUSTOMER, is_active=True).order_by("username"),
        empty_label="Select a customer",
    )
    vehicle = VehicleChoiceField(
        queryset=Vehicle.objects.select_related("owner"),
        empty_label="Select a vehicle",
        show_owner=True,
        widget=TaggedSelect(tag_name="data-owner", tag_getter=lambda vehicle: vehicle.owner_id),
    )
    mechanic = UserChoiceField(
        queryset=User.objects.filter(role=User.Role.MECHANIC, is_active=True).select_related("workshop").order_by("username"),
        required=False,
        empty_label="Not assigned yet",
        widget=TaggedSelect(tag_name="data-workshop", tag_getter=lambda mechanic: mechanic.workshop_id),
    )
    status = forms.ChoiceField(choices=Booking.STATUS_CHOICES)

    field_order = [
        "customer", "workshop", "vehicle", "booking_date", "booking_time", "service_type",
        "other_service", "notes", "mechanic", "status",
    ]

    class Meta(BookingForm.Meta):
        fields = [
            "customer", "workshop", "vehicle", "booking_date", "booking_time", "service_type",
            "notes", "mechanic", "status",
            "same_issue_returned",
            "courtesy_vehicle_requested", "courtesy_vehicle_start", "courtesy_vehicle_end",
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields["workshop"].disabled = False
        self.fields["workshop"].help_text = ""

        # A new booking starts as Pending or Confirmed. A quote is made from the quote page, so
        # "Quote received" is only listed for a booking that is already quoted.
        current = self.instance.status if self.instance.pk else None
        allowed = {"PENDING", "CONFIRMED"} if current is None else {s for s, _ in Booking.STATUS_CHOICES} - {"QUOTED"}
        if current:
            allowed.add(current)
        self.fields["status"].choices = [(s, label) for s, label in Booking.STATUS_CHOICES if s in allowed]
        if current is None:
            self.initial.setdefault("status", "PENDING")

        if user is not None and user.is_mechanic:
            # The earlier-time alert is the customer's own choice, so mechanics never see it.
            del self.fields["earlier_slot_opt_in"]
            workshop = user.workshop
            del self.fields["workshop"]
            self.instance.workshop = workshop
            self.fields["mechanic"].queryset = User.objects.filter(
                role=User.Role.MECHANIC, workshop=workshop, is_active=True,
            ).order_by("username")
            self.fields["booking_time"].choices = [("", "Select a time")] + scheduling.slot_choices(workshop)
            self.fields["booking_time"].help_text = (
                f"{workshop.name} is open {workshop.hours_text}. Each booking is {scheduling.SLOT_MINUTES} minutes."
            )

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get("customer")
        vehicle = cleaned_data.get("vehicle")
        if customer and vehicle and vehicle.owner_id != customer.pk:
            self.add_error("vehicle", "This vehicle belongs to a different customer.")
        return cleaned_data


class QuoteForm(BootstrapFormMixin, forms.Form):
    quote_notes = forms.CharField(
        label="Quote details",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Parts, labour and any exclusions"}),
    )
    mechanic = UserChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Choose a mechanic",
    )

    def __init__(self, *args, booking=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.booking = booking
        if not user or not user.is_admin_role:
            del self.fields["mechanic"]
        elif booking:
            self.fields["mechanic"].queryset = User.objects.filter(
                role=User.Role.MECHANIC,
                workshop=booking.workshop,
                is_active=True,
            ).order_by("username")


class QuotePartForm(BootstrapFormMixin, forms.Form):
    source = forms.ChoiceField(
        choices=[
            ("", "Choose a part type"),
            ("STOCK", "Use a stocked part"),
            ("MANUAL", "Add a manual/estimated part"),
        ],
        required=False,
        label="Part type",
    )
    stock_item = forms.ModelChoiceField(
        queryset=StockItem.objects.none(),
        label="Part",
        empty_label="Select a stocked part",
        required=False,
    )
    manual_description = forms.CharField(
        max_length=150,
        required=False,
        label="Manual part description",
    )
    estimated_unit_price = forms.DecimalField(
        min_value=0,
        max_digits=8,
        decimal_places=2,
        required=False,
        label="Estimated unit cost",
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
    )
    quantity = forms.IntegerField(min_value=1, required=False)

    def __init__(self, *args, workshop=None, vehicle=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workshop is None:
            return
        stock = StockItem.objects.filter(
            workshop=workshop,
            quantity__gt=0,
            part__is_active=True,
        ).select_related("part")
        if vehicle is not None:
            matching_parts = parts_matching(vehicle.make, vehicle.model, vehicle.year)
            stock = stock.filter(part__in=matching_parts)
        self.fields["stock_item"].queryset = stock
        self.fields["stock_item"].label_from_instance = (
            lambda item: f"{item.part.part_number} - {item.part.name} "
            f"(${item.price:.2f} each; {item.quantity} in stock)"
        )

    def clean(self):
        cleaned_data = super().clean()
        source = cleaned_data.get("source")
        stock_item = cleaned_data.get("stock_item")
        manual_description = (cleaned_data.get("manual_description") or "").strip()
        quantity = cleaned_data.get("quantity")

        if not source:
            if (
                stock_item
                or manual_description
                or cleaned_data.get("estimated_unit_price") is not None
                or quantity
            ):
                self.add_error("source", "Choose whether this is a stocked or manual part.")
            return cleaned_data

        if quantity is None:
            self.add_error("quantity", "Enter a quantity.")
        if source == "STOCK" and stock_item is None:
            self.add_error("stock_item", "Select a part from this workshop's stock.")
        if source == "MANUAL":
            if not manual_description:
                self.add_error("manual_description", "Describe the part.")
            if cleaned_data.get("estimated_unit_price") is None:
                self.add_error("estimated_unit_price", "Enter an estimated unit cost.")
        cleaned_data["manual_description"] = manual_description
        return cleaned_data


class QuotePartFormSetBase(forms.BaseFormSet):
    def __init__(self, *args, workshop=None, **kwargs):
        self.workshop = workshop
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        quantities = {}
        for form in self.forms:
            data = getattr(form, "cleaned_data", {})
            if not data or data.get("DELETE"):
                continue
            if data.get("source") != "STOCK":
                continue
            stock_item = data.get("stock_item")
            if stock_item is not None:
                quantities[stock_item.pk] = quantities.get(stock_item.pk, 0) + data["quantity"]

        if not quantities:
            return
        available = dict(
            StockItem.objects.filter(
                pk__in=quantities,
                workshop=self.workshop,
            ).values_list("pk", "quantity")
        )
        for stock_item_id, requested in quantities.items():
            if requested > available.get(stock_item_id, 0):
                raise forms.ValidationError(
                    "The requested quantity exceeds the workshop's current stock."
                )


QuotePartFormSet = forms.formset_factory(
    QuotePartForm,
    formset=QuotePartFormSetBase,
    extra=1,
    can_delete=True,
    max_num=20,
    validate_max=True,
)


class QuoteLabourForm(BootstrapFormMixin, forms.Form):
    description = forms.CharField(max_length=150, label="Labour")
    charge = forms.DecimalField(
        min_value=0,
        max_digits=8,
        decimal_places=2,
        label="Labour charge",
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
    )


QuoteLabourFormSet = forms.formset_factory(
    QuoteLabourForm,
    extra=1,
    max_num=1,
    validate_max=True,
)
