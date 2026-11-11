from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse

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

    notification = Notification.objects.create(
        recipient=instance.customer,
        booking=instance,
        message=f"Booking #{instance.pk} is now {instance.get_status_display()}.",
    )
    updates_url = f"{settings.SITE_URL.rstrip('/')}{reverse('notifications:list')}"
    send_mail(
        subject="GarageLog booking update",
        message=(
            f"Hi {instance.customer.first_name or instance.customer.username},\n\n"
            f"{notification.message}\n\n"
            f"View your updates: {updates_url}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[instance.customer.email],
    )
