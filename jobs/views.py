from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User

from .models import JobCard


class JobCardQuerysetMixin:
    """Mechanics only ever get their own job cards. Admins get all of them.

    Anything outside that slice is a 404, so URLs cannot be guessed to read it.
    """

    def get_queryset(self):
        job_cards = JobCard.objects.select_related(
            "booking",
            "booking__vehicle",
            "booking__customer",
            "booking__workshop",
            "mechanic",
        ).order_by("-created_at")

        user = self.request.user
        if user.is_admin_role:
            return job_cards
        return job_cards.filter(mechanic=user)


class JobCardListView(JobCardQuerysetMixin, RoleRequiredMixin, ListView):
    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)
    template_name = "jobs/jobcard_list.html"
    context_object_name = "job_cards"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "All job cards" if self.request.user.is_admin_role else "My job cards"
        return context


class JobCardDetailView(JobCardQuerysetMixin, RoleRequiredMixin, UpdateView):
    """Shows one job card with the booking details, and lets the mechanic update it."""

    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)
    model = JobCard
    fields = ["description", "work_done", "status"]
    template_name = "jobs/jobcard_form.html"
    context_object_name = "job_card"
    success_url = reverse_lazy("jobcard_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for name, field in form.fields.items():
            field.widget.attrs["class"] = "form-select" if name == "status" else "form-control"
        form.fields["description"].widget.attrs["rows"] = 3
        form.fields["work_done"].widget.attrs["rows"] = 5
        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "The job card has been updated.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Job card #{self.object.pk}"
        return context