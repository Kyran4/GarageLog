from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from .models import Notification


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related(
            "booking",
            "booking__customer",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unread_count"] = self.get_queryset().filter(read_at__isnull=True).count()
        return context


class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(
            Notification,
            pk=pk,
            recipient=request.user,
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return redirect("notifications:list")


class MarkAllNotificationsReadView(LoginRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        messages.success(request, "All updates have been marked as read.")
        return redirect("notifications:list")
