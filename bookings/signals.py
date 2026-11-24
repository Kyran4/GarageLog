from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

from . import scheduling
from .models import Booking, EarlierSlotOffer


def _notify_customer(booking, message):
    notification = Notification.objects.create(
        recipient=booking.customer,
        booking=booking,
        message=message,
    )
    updates_url = f"{settings.SITE_URL.rstrip('/')}{reverse('notifications:list')}"
    send_mail(
        subject="GarageLog booking update",
        message=(
            f"Hi {booking.customer.first_name or booking.customer.username},\n\n"
            f"{notification.message}\n\n"
            f"View your updates: {updates_url}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[booking.customer.email],
    )
    return notification


def _slot_has_vehicle_or_mechanic_clash(candidate, source):
    clashes = Booking.objects.filter(
        booking_date=source.booking_date,
        booking_time=source.booking_time,
        status__in=Booking.ACTIVE_STATUSES,
    )
    if candidate.vehicle_id and clashes.filter(vehicle_id=candidate.vehicle_id).exists():
        return True
    return bool(candidate.mechanic_id and clashes.filter(mechanic_id=candidate.mechanic_id).exists())


def offer_earlier_slot_to_next_customer(source):
    if (
        source.status != "CANCELLED"
        or source.starts_at < timezone.now()
        or scheduling.booked_count(source.workshop, source.booking_date, source.booking_time)
        >= scheduling.capacity(source.workshop)
        or source.offers_for_cancelled_slot.filter(status=EarlierSlotOffer.STATUS_PENDING).exists()
    ):
        return

    candidates = (
        Booking.objects.filter(
            workshop_id=source.workshop_id,
            booking_date=source.booking_date,
            booking_time__gt=source.booking_time,
            status__in=Booking.ACTIVE_STATUSES,
            earlier_slot_opt_in=True,
        )
        .exclude(pk=source.pk)
        .exclude(earlier_slot_offers__source_booking=source)
        .exclude(earlier_slot_offers__status=EarlierSlotOffer.STATUS_PENDING)
        .select_related("customer")
        .order_by("created_at", "pk")
    )
    for candidate in candidates:
        if not candidate.is_upcoming or _slot_has_vehicle_or_mechanic_clash(candidate, source):
            continue

        EarlierSlotOffer.objects.create(
            source_booking=source,
            target_booking=candidate,
        )
        _notify_customer(
            candidate,
            (
                f"An earlier time is available for booking #{candidate.pk}: "
                f"{source.booking_date.day} {source.booking_date:%b} at "
                f"{scheduling.format_time(source.booking_time)}."
            ),
        )
        return


@receiver(pre_save, sender=Booking)
def remember_previous_booking_status(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._previous_booking_state = None
        return
    instance._previous_booking_state = sender.objects.filter(pk=instance.pk).values(
        "status", "workshop_id", "booking_date", "booking_time", "earlier_slot_opt_in",
    ).first()


@receiver(post_save, sender=Booking)
def notify_customer_of_booking_status_change(sender, instance, created, raw=False, **kwargs):
    previous_state = getattr(instance, "_previous_booking_state", None)
    if raw or created or previous_state is None:
        return

    previous_status = previous_state["status"]
    previous_schedule = (
        previous_state["workshop_id"],
        previous_state["booking_date"],
        previous_state["booking_time"],
        previous_state["earlier_slot_opt_in"],
    )
    current_schedule = (
        instance.workshop_id,
        instance.booking_date,
        instance.booking_time,
        instance.earlier_slot_opt_in,
    )

    if previous_status != instance.status and instance.status == "QUOTED":
        message = f"Booking #{instance.pk} has received a quote."
    elif previous_status != instance.status and instance.status == "CONFIRMED" and previous_status == "QUOTED":
        message = f"Booking #{instance.pk} quote accepted; the booking is confirmed."
    elif previous_status != instance.status:
        message = f"Booking #{instance.pk} is now {instance.get_status_display()}."
    else:
        message = None

    if message:
        _notify_customer(instance, message)

    if previous_status == "CANCELLED" and (
        instance.status != "CANCELLED" or previous_schedule != current_schedule
    ):
        for offer in instance.offers_for_cancelled_slot.filter(
            status=EarlierSlotOffer.STATUS_PENDING,
        ).select_related("target_booking__customer"):
            offer.status = EarlierSlotOffer.STATUS_WITHDRAWN
            offer.responded_at = timezone.now()
            offer.save(update_fields=["status", "responded_at"])
            _notify_customer(
                offer.target_booking,
                f"The earlier-time offer for booking #{offer.target_booking_id} is no longer available.",
            )

    if previous_schedule != current_schedule or instance.status not in Booking.ACTIVE_STATUSES:
        pending_offers = list(
            instance.earlier_slot_offers.filter(status=EarlierSlotOffer.STATUS_PENDING)
            .select_related("source_booking")
        )
        for offer in pending_offers:
            offer.status = EarlierSlotOffer.STATUS_WITHDRAWN
            offer.responded_at = timezone.now()
            offer.save(update_fields=["status", "responded_at"])
            offer_earlier_slot_to_next_customer(offer.source_booking)

    if previous_status in Booking.ACTIVE_STATUSES and instance.status == "CANCELLED":
        offer_earlier_slot_to_next_customer(instance)
