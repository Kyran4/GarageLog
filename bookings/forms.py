import datetime

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.models import User
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
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields["workshop"].disabled = False
        self.fields["workshop"].help_text = ""

        if user is not None and user.is_mechanic:
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
