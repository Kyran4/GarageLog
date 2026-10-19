from django import forms
from django.utils import timezone
from .models import Booking


class BookingForm(forms.ModelForm):

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