import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from vehicles.models import Vehicle
from workshops.models import Workshop

from . import scheduling
from .forms import BookingForm


def frozen_now(date, hour, minute=0):
    """Patch 'now' to a moment on `date`, to test rules about times that have already passed."""
    moment = timezone.make_aware(datetime.datetime.combine(date, datetime.time(hour, minute)))
    return mock.patch("django.utils.timezone.now", return_value=moment)


class BookingFormTests(TestCase):

    def setUp(self):
        self.workshop = Workshop.objects.create(name="Central Workshop")
        self.customer = User.objects.create_user("casey", "casey@example.com", role=User.Role.CUSTOMER)
        self.vehicle = Vehicle.objects.create(
            owner=self.customer, plate="ABC123", make="Toyota", model="Corolla", year=2015,
        )
        self.open_day = scheduling.next_open_date()

    def make_form(self, **overrides):
        data = {
            "workshop": self.workshop.pk,
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

    # ----------------------------------------------------------- workshops

    def test_workshop_is_required(self):
        form = self.make_form(workshop="")

        self.assertFalse(form.is_valid())
        self.assertIn("workshop", form.errors)

    def test_inactive_workshop_cannot_be_chosen(self):
        closed = Workshop.objects.create(name="Closed Workshop", is_active=False)

        form = self.make_form(workshop=closed.pk)

        self.assertFalse(form.is_valid())
        self.assertIn("workshop", form.errors)

    def test_each_workshop_uses_its_own_opening_hours(self):
        late = Workshop.objects.create(
            name="Late Workshop", open_time=datetime.time(10, 0), close_time=datetime.time(19, 0),
        )

        # 9:00 am is fine at the central workshop but before the late workshop opens.
        self.assertTrue(self.make_form(booking_time="09:00").is_valid())
        too_early = self.make_form(workshop=late.pk, booking_time="09:00")
        self.assertFalse(too_early.is_valid())
        self.assertIn("outside Late Workshop's hours", too_early.errors["booking_time"][0])
        # 6:00 pm only exists at the late workshop.
        self.assertTrue(self.make_form(workshop=late.pk, booking_time="18:00").is_valid())
        self.assertFalse(self.make_form(booking_time="18:00").is_valid())

    def test_weekend_opening_is_per_workshop(self):
        saturday = self.open_day + datetime.timedelta(days=(5 - self.open_day.weekday()))
        weekends = Workshop.objects.create(name="Weekend Workshop", open_saturday=True)

        self.assertTrue(self.make_form(workshop=weekends.pk, booking_date=saturday.isoformat()).is_valid())
        self.assertFalse(self.make_form(booking_date=saturday.isoformat()).is_valid())

    def test_a_single_active_workshop_is_preselected(self):
        form = BookingForm(user=self.customer)
        self.assertEqual(form.initial["workshop"], self.workshop.pk)

        Workshop.objects.create(name="Second Workshop")
        self.assertNotIn("workshop", BookingForm(user=self.customer).initial)
