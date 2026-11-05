from .models import Notification


def unread_notification_count(request):
    count = 0
    if request.user.is_authenticated:
        count = Notification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).count()
    return {"unread_notification_count": count}
