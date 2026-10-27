import datetime

from django import forms
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.models import User
from vehicles.models import Vehicle

from . import scheduling
from .models import Booking


def _parse_time(value):
    return datetime.datetime.strptime(value, "%H:%M").time()


class OwnerAwareSelect(forms.Select):
    """A select whose vehicle options carry a data-owner attribute, so the page can show only
    the vehicles that belong to the selected customer."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-owner"] = instance.owner_id
        return option


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

    vehicle = VehicleChoiceField(
        queryset=Vehicle.objects.none(),
        empty_label="Select a vehicle",
    )

    booking_time = forms.TypedChoiceField(
        label="Time",
        choices=[("", "Select a time")] + scheduling.slot_choices(),
        coerce=_parse_time,
        empty_value=None,
        help_text=f"Open {scheduling.OPEN_DAYS_TEXT}, {scheduling.format_time(scheduling.OPEN_TIME)} to "
                  f"{scheduling.format_time(scheduling.CLOSE_TIME)}. Each booking is "
                  f"{scheduling.SLOT_MINUTES} minutes.",
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
            "vehicle",
            "booking_date",
            "booking_time",
            "service_type",
            "notes",
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

        self.fields["booking_date"].widget.attrs["min"] = timezone.localdate().isoformat()
        if user is not None:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(owner=user)

        booking = self.instance
        if booking.pk:
            # Editing: show the saved time in the dropdown, and show a custom service as "Other".
            self.initial["booking_time"] = booking.booking_time.strftime("%H:%M")
            known = {value for value, _ in self.SERVICE_CHOICES if value}
            if booking.service_type not in known:
                self.initial["service_type"] = "Other"
                self.initial["other_service"] = booking.service_type

    def _schedule_changed(self):
        return self.instance.pk is None or bool({"booking_date", "booking_time"} & set(self.changed_data))

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

        date = cleaned_data.get("booking_date")
        time = cleaned_data.get("booking_time")
        if date and time and self._schedule_changed():
            closed = scheduling.closed_reason(date)
            if closed:
                self.add_error("booking_date", closed)
            elif scheduling.starts_at(date, time) < timezone.now():
                self.add_error("booking_time", "That time has already passed. Please choose a later time.")

        return cleaned_data

    def validate_constraints(self):
        # Clashes are checked in Booking.clean() with friendlier messages. The database
        # constraints stay in place as a safety net.
        pass


class AdminBookingForm(BookingForm):
    """Admins book on behalf of a customer and can assign a mechanic and set the status."""

    customer = UserChoiceField(
        queryset=User.objects.filter(role=User.Role.CUSTOMER, is_active=True).order_by("username"),
        empty_label="Select a customer",
    )
    mechanic = UserChoiceField(
        queryset=User.objects.filter(role=User.Role.MECHANIC, is_active=True).order_by("username"),
        required=False,
        empty_label="Not assigned yet",
    )
    status = forms.ChoiceField(choices=Booking.STATUS_CHOICES)

    field_order = [
        "customer", "vehicle", "booking_date", "booking_time", "service_type",
        "other_service", "notes", "mechanic", "status",
    ]

    class Meta(BookingForm.Meta):
        fields = [
            "customer", "vehicle", "booking_date", "booking_time", "service_type",
            "notes", "mechanic", "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"] = VehicleChoiceField(
            queryset=Vehicle.objects.select_related("owner"),
            empty_label="Select a vehicle",
            show_owner=True,
            widget=OwnerAwareSelect,
        )
        self.fields["vehicle"].widget.attrs["class"] = "form-select"

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get("customer")
        vehicle = cleaned_data.get("vehicle")
        if customer and vehicle and vehicle.owner_id != customer.pk:
            self.add_error("vehicle", "This vehicle belongs to a different customer.")
        return cleaned_data
