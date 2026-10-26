from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .forms import BookingForm


class BookingFormTests(TestCase):

    def test_past_date_is_rejected(self):
        yesterday = timezone.localdate() - timedelta(days=1)

        form = BookingForm(data={
            "booking_date": yesterday.isoformat(),
            "booking_time": "10:00",
            "service_type": "Oil Change",
            "notes": "Test booking",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("booking_date", form.errors)


    def test_future_date_is_accepted(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        form = BookingForm(data={
            "booking_date": tomorrow.isoformat(),
            "booking_time": "10:00",
            "service_type": "Oil Change",
            "notes": "Test booking",
        })

        self.assertTrue(form.is_valid())

    def test_other_service_is_required(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        form = BookingForm(data={
            "booking_date": tomorrow.isoformat(),
            "booking_time": "10:00",
            "service_type": "Other",
            "other_service": "",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("other_service", form.errors)

    def test_custom_service_is_accepted(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        form = BookingForm(data={
            "booking_date": tomorrow.isoformat(),
            "booking_time": "10:00",
            "service_type": "Other",
            "other_service": "Air Conditioning Repair",
        })

        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["service_type"],
            "Air Conditioning Repair"
        )