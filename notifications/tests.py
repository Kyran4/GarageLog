import pytest
from django.core import mail
from django.urls import reverse

from .models import Notification

pytestmark = pytest.mark.django_db


def test_booking_status_changes_create_in_app_updates_for_the_customer(customer, vehicle, make_booking):
    mail.outbox.clear()
    booking = make_booking(customer, vehicle)
    assert Notification.objects.count() == 0
    assert mail.outbox == []

    booking.status = "CONFIRMED"
    booking.save(update_fields=["status"])
    assert Notification.objects.count() == 1
    update = Notification.objects.get()
    assert update.recipient == customer
    assert update.booking == booking
    assert update.message == f"Booking #{booking.pk} is now Confirmed."
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [customer.email]
    assert update.message in mail.outbox[0].body
    assert "http://127.0.0.1:8000/updates/" in mail.outbox[0].body

    booking.status = "IN_PROGRESS"
    booking.save(update_fields=["status"])
    assert Notification.objects.count() == 2
    assert len(mail.outbox) == 2

    booking.notes = "No status change"
    booking.save(update_fields=["notes"])
    assert Notification.objects.count() == 2
    assert len(mail.outbox) == 2


def test_updates_page_is_login_required_and_shows_only_the_users_updates(
    client, customer, make_user, vehicle, make_vehicle, make_booking,
):
    booking = make_booking(customer, vehicle)
    own = Notification.objects.create(
        recipient=customer,
        booking=booking,
        message="Your booking was confirmed.",
    )
    other_customer = make_user("notification-other")
    other_vehicle = make_vehicle(other_customer, plate="OTHER1")
    other_booking = make_booking(other_customer, other_vehicle, time=booking.booking_time.replace(hour=11))
    Notification.objects.create(
        recipient=other_customer,
        booking=other_booking,
        message="Private update.",
    )

    url = reverse("notifications:list")
    anonymous_response = client.get(url)
    assert anonymous_response.status_code == 302
    assert anonymous_response.url.startswith(reverse("accounts:login"))

    client.force_login(customer)
    response = client.get(url)
    assert response.status_code == 200
    assert list(response.context["notifications"]) == [own]
    assert response.context["unread_count"] == 1
    assert b"Private update" not in response.content
    assert b"1 unread" in response.content


def test_user_can_mark_their_own_updates_read_but_not_another_users(
    client, customer, make_user,
):
    own = Notification.objects.create(recipient=customer, message="Own update.")
    other_customer = make_user("notification-owner")
    other = Notification.objects.create(recipient=other_customer, message="Private update.")
    client.force_login(customer)

    own_url = reverse("notifications:read", kwargs={"pk": own.pk})
    response = client.get(own_url)
    assert response.status_code == 405
    response = client.post(own_url)
    assert response.status_code == 302
    own.refresh_from_db()
    assert own.read_at is not None

    response = client.post(reverse("notifications:read", kwargs={"pk": other.pk}))
    assert response.status_code == 404


def test_user_can_mark_all_their_notifications_read_without_affecting_others(
    client, customer, make_user,
):
    first = Notification.objects.create(recipient=customer, message="First update.")
    second_user = make_user("another-notification-user")
    other = Notification.objects.create(recipient=second_user, message="Other update.")
    client.force_login(customer)

    response = client.post(reverse("notifications:read_all"))

    assert response.status_code == 302
    first.refresh_from_db()
    other.refresh_from_db()
    assert first.read_at is not None
    assert second_user.notifications.filter(read_at__isnull=True).exists()
    assert other.read_at is None
