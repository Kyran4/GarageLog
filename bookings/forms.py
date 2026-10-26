from django import forms
from django.utils import timezone
from .models import Booking


class BookingForm(forms.ModelForm):

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
            "booking_date",
            "booking_time",
            "service_type",
            "notes",
        ]

        widgets = {
            "booking_date": forms.DateInput(
                attrs={"type": "date"}
            ),
            "booking_time": forms.TimeInput(
                attrs={"type": "time"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3}
            ),
        }

    def clean_booking_date(self):
        date = self.cleaned_data["booking_date"]

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

        return cleaned_data