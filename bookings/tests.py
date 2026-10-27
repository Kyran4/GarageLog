import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from vehicles.models import Vehicle

from . import scheduling
from .forms import BookingForm


def frozen_now(date, hour, minute=0):
    """Patch 'now' to a moment on `date`, to test rules about times that have already passed."""
    moment = timezone.make_aware(datetime.datetime.combine(date, datetime.time(hour, minute)))
    return mock.patch("django.utils.timezone.now", return_value=moment)


class BookingFormTests(TestCase):

    def setUp(self):
        self.customer = User.objects.create_user("casey", "casey@example.com", role=User.Role.CUSTOMER)
        self.vehicle = Vehicle.objects.create(
            owner=self.customer, plate="ABC123", make="Toyota", model="Corolla", year=2015,
        )
        self.open_day = scheduling.next_open_date()

    def make_form(self, **overrides):
        data = {
            "vehicle": self.vehicle.pk,
            "booking_date": self.open_day.isoformat(),
            "booking_time": "10:00",
            "service_type": "Oil Change",
            "notes": "Test booking",
        }
        data.update(overrides)
        return BookingForm(data=data, user=self.customer)

    def test_past_date_is_rejected(self):
        yesterday = timezone.localdate() - datetime.timedelta(days=1)

        form = self.make_form(booking_date=yesterday.isoformat())

        self.assertFalse(form.is_valid())
        self.assertIn("booking_date", form.errors)

    def test_future_date_is_accepted(self):
        form = self.make_form()

        self.assertTrue(form.is_valid(), form.errors)

    def test_other_service_is_required(self):
        form = self.make_form(service_type="Other", other_service="")

        self.assertFalse(form.is_valid())
        self.assertIn("other_service", form.errors)

    def test_custom_service_is_accepted(self):
        form = self.make_form(service_type="Other", other_service="Air Conditioning Repair")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["service_type"],
            "Air Conditioning Repair"
        )

    def test_vehicle_is_required(self):
        form = self.make_form(vehicle="")

        self.assertFalse(form.is_valid())
        self.assertIn("vehicle", form.errors)

    def test_cannot_book_someone_elses_vehicle(self):
        other = User.objects.create_user("sam", "sam@example.com", role=User.Role.CUSTOMER)
        theirs = Vehicle.objects.create(owner=other, plate="XYZ789", make="Mazda", model="3", year=2018)

        form = self.make_form(vehicle=theirs.pk)

        self.assertFalse(form.is_valid())
        self.assertIn("vehicle", form.errors)

    def test_weekend_is_rejected(self):
        saturday = self.open_day + datetime.timedelta(days=(5 - self.open_day.weekday()) % 7 or 7)

        form = self.make_form(booking_date=saturday.isoformat())

        self.assertFalse(form.is_valid())
        self.assertIn("closed", form.errors["booking_date"][0])

    def test_time_outside_the_slots_is_rejected(self):
        for bad_time in ("10:30", "07:00", "17:00", "23:00"):
            with self.subTest(time=bad_time):
                self.assertIn("booking_time", self.make_form(booking_time=bad_time).errors)

    def test_time_earlier_today_is_rejected_but_later_today_is_fine(self):
        with frozen_now(self.open_day, 13):
            self.assertIn("booking_time", self.make_form(
                booking_date=self.open_day.isoformat(), booking_time="09:00").errors)
            self.assertTrue(self.make_form(
                booking_date=self.open_day.isoformat(), booking_time="15:00").is_valid())
