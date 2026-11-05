from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from notifications.models import Notification

from .models import Booking


@receiver(pre_save, sender=Booking)
def remember_previous_booking_status(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = (
        sender.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )


@receiver(post_save, sender=Booking)
def notify_customer_of_booking_status_change(sender, instance, created, raw=False, **kwargs):
    previous_status = getattr(instance, "_previous_status", None)
    if raw or created or previous_status is None or previous_status == instance.status:
        return

    Notification.objects.create(
        recipient=instance.customer,
        booking=instance,
        message=f"Booking #{instance.pk} is now {instance.get_status_display()}.",
    )
