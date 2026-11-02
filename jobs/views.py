from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from bookings.models import Booking

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
    def get_success_url(self):
        return reverse("booking_detail", kwargs={"pk": self.object.booking_id})

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


class JobCardCreateView(RoleRequiredMixin, View):
    """Creates the job card for a booking. Only reachable by POST (the button on the booking page)."""

    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)

    def post(self, request, booking_id):
        user = request.user

        # Same rule as the booking pages: a mechanic only reaches bookings at their own workshop.
        bookings = Booking.objects.select_related("workshop", "mechanic")
        if user.is_mechanic:
            bookings = bookings.filter(workshop_id=user.workshop_id)
        booking = get_object_or_404(bookings, pk=booking_id)

        back_to_booking = redirect("booking_detail", pk=booking.pk)

        if booking.status != "CONFIRMED":
            messages.error(request, "Only confirmed bookings can have a job card.")
            return back_to_booking

        if booking.workshop.is_parts_warehouse:
            messages.error(request, "The parts warehouse does not take bookings, so it has no job cards.")
            return back_to_booking

        # Use the booking's mechanic. A mechanic with no one assigned takes the job themselves.
        mechanic = booking.mechanic
        if mechanic is None and user.is_mechanic:
            mechanic = user
        if mechanic is None:
            messages.error(request, "Assign a mechanic to this booking first, then create the job card.")
            return back_to_booking

        job_card, created = JobCard.objects.get_or_create(
            booking=booking,
            defaults={"mechanic": mechanic},
        )
        if not created:
            messages.info(request, "This booking already has a job card.")
            return back_to_booking

        messages.success(request, "The job card has been created.")
        if user.is_admin_role or job_card.mechanic_id == user.pk:
            return redirect("jobcard_detail", pk=job_card.pk)
        return back_to_booking