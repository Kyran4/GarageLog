import calendar
import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import AdminRequiredMixin, RoleRequiredMixin
from accounts.models import User
from vehicles.models import Vehicle
from workshops.models import Workshop

from . import scheduling
from .forms import BookingForm, StaffBookingForm
from .models import Booking


class BookingQuerysetMixin(LoginRequiredMixin):
    """Each role only ever sees its own slice of the bookings.

    Customers see their own bookings, mechanics see every booking at the workshop they are
    assigned to, and admins see everything. Anything outside that slice is a 404, so URLs
    cannot be guessed to read it.
    """

    def get_queryset(self):
        user = self.request.user
        bookings = Booking.objects.select_related("customer", "mechanic", "vehicle", "workshop")
        if user.is_admin_role:
            return bookings
        if user.is_mechanic:
            return bookings.filter(workshop_id=user.workshop_id) if user.workshop_id else bookings.none()
        return bookings.filter(customer=user)


class BookingListView(BookingQuerysetMixin, ListView):
    template_name = "bookings/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 20

    SORT_OPTIONS = {
        "date_asc": ("Oldest date", ("booking_date", "booking_time")),
        "date_desc": ("Newest date", ("-booking_date", "-booking_time")),
        "time_asc": ("Time (earliest first)", ("booking_time", "booking_date")),
        "time_desc": ("Time (latest first)", ("-booking_time", "booking_date")),
        "service": ("Service (A-Z)", ("service_type", "-booking_date", "-booking_time")),
        "status": ("Status", ("status", "-booking_date", "-booking_time")),
    }

    def _is_staff(self):
        user = self.request.user
        return user.is_admin_role or user.is_mechanic

    def get_selected_month(self):
        try:
            month = datetime.datetime.strptime(
                self.request.GET.get("month", ""), "%Y-%m"
            ).date().replace(day=1)
            if not 1900 <= month.year <= 9998:
                raise ValueError
            return month
        except ValueError:
            return timezone.localdate().replace(day=1)

    def get_view_mode(self):
        return "calendar" if self.request.GET.get("view") == "calendar" else "list"

    def get_paginate_by(self, queryset):
        return None if self.get_view_mode() == "calendar" else self.paginate_by


    def get_queryset(self):
        bookings = super().get_queryset()

        user = self.request.user

        # Hide cancelled bookings from customers only
        if user.is_customer:
            bookings = bookings.exclude(status="CANCELLED")

        # Staff (mechanics and admins) can filter by status
        if self._is_staff():
            status = self.request.GET.get("status", "")
            if status in dict(Booking.STATUS_CHOICES):
                bookings = bookings.filter(status=status)

        if self.get_view_mode() == "calendar":
            month = self.get_selected_month()
            next_month = (
                month.replace(day=28) + datetime.timedelta(days=4)
            ).replace(day=1)
            bookings = bookings.filter(
                booking_date__gte=month,
                booking_date__lt=next_month,
            ).order_by("booking_date", "booking_time")
        else:
            selected_sort = self.request.GET.get("sort", "date_desc")
            ordering = self.SORT_OPTIONS.get(
                selected_sort, self.SORT_OPTIONS["date_desc"]
            )[1]
            bookings = bookings.order_by(*ordering)

        return bookings


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["is_admin"] = user.is_admin_role
        context["is_mechanic"] = user.is_mechanic
        context["can_create"] = True
        if user.is_admin_role:
            context["page_title"] = "All bookings"
        elif user.is_mechanic:
            context["page_title"] = f"Bookings at {user.workshop}" if user.workshop_id else "Bookings"
        else:
            context["page_title"] = "My bookings"
        context["view_mode"] = self.get_view_mode()
        context["sort_options"] = [
            (key, label) for key, (label, _) in self.SORT_OPTIONS.items()
        ]
        selected_sort = self.request.GET.get("sort", "date_desc")
        context["selected_sort"] = (
            selected_sort if selected_sort in self.SORT_OPTIONS else "date_desc"
        )
        month = self.get_selected_month()
        context["selected_month"] = month
        context["month_label"] = month.strftime("%B %Y")
        context["previous_month"] = (month - datetime.timedelta(days=1)).replace(day=1)
        context["next_month"] = (
            month.replace(day=28) + datetime.timedelta(days=4)
        ).replace(day=1)
        if context["view_mode"] == "calendar":
            bookings_by_date = {}
            for booking in context["bookings"]:
                bookings_by_date.setdefault(booking.booking_date, []).append(booking)
            context["calendar_weeks"] = [
                [
                    {
                        "date": day,
                        "in_month": day.month == month.month,
                        "bookings": bookings_by_date.get(day, []),
                    }
                    for day in week
                ]
                for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
                    month.year, month.month
                )
            ]
        if self._is_staff():
            current = self.request.GET.get("status", "")
            context["status_filter"] = current if current in dict(Booking.STATUS_CHOICES) else ""
            context["status_options"] = [("", "All")] + Booking.STATUS_CHOICES
        return context


class BookingDetailView(BookingQuerysetMixin, DetailView):
    template_name = "bookings/booking_detail.html"
    context_object_name = "booking"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["can_edit"] = self.object.can_be_edited_by(user)
        context["can_cancel"] = self.object.can_be_cancelled_by(user)
        context["is_admin"] = user.is_admin_role
        return context


class BookingSaveMixin:
    """Shared by the create and edit views: picks the form for the role and saves safely."""

    template_name = "bookings/create_booking.html"

    def get_form_class(self):
        return BookingForm if self.request.user.is_customer else StaffBookingForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("booking_detail", kwargs={"pk": self.object.pk})

    def save_booking(self, form):
        """Save inside a transaction and re-check the slot, so two people booking the same
        slot at the same moment cannot both get it. Returns True when saved."""
        booking = form.instance
        try:
            with transaction.atomic():
                scheduling.lock_capacity(booking.workshop)
                if (
                    booking.status in Booking.ACTIVE_STATUSES
                    and scheduling.booked_count(booking.workshop, booking.booking_date, booking.booking_time, booking.pk)
                    >= scheduling.capacity(booking.workshop)
                ):
                    form.add_error("booking_time", "That time was just taken. Please choose another time.")
                    return False
                self.object = form.save()
        except IntegrityError:
            form.add_error(None, "That time was just taken by another booking. Please choose a different time.")
            return False
        return True


class BookingCreateView(BookingSaveMixin, RoleRequiredMixin, CreateView):
    allowed_roles = (User.Role.CUSTOMER, User.Role.MECHANIC, User.Role.ADMIN)

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated:
            if user.is_customer:
                if not Workshop.objects.bookable().exists():
                    messages.info(request, "No workshops are taking bookings yet. Please check back soon.")
                    return redirect("dashboard")
                if not Vehicle.objects.filter(owner=user).exists():
                    messages.info(request, "Add your vehicle first, then you can book a service for it.")
                    return redirect("vehicles:create")
            elif user.is_mechanic and not user.workshop_id:
                messages.error(request, "You aren't assigned to a workshop yet, so you can't make bookings. "
                                        "Ask an admin to assign you.")
                return redirect("dashboard")
            elif user.is_mechanic and user.workshop.is_parts_warehouse:
                messages.info(request, f"{user.workshop.name} is the parts warehouse and doesn't take bookings.")
                return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        vehicle_id = self.request.GET.get("vehicle")
        if vehicle_id and vehicle_id.isdigit():
            initial["vehicle"] = vehicle_id
            if not self.request.user.is_customer:
                # Booking from a vehicle's page: start with that vehicle's owner selected.
                owner_id = Vehicle.objects.filter(pk=vehicle_id).values_list("owner_id", flat=True).first()
                if owner_id:
                    initial["customer"] = owner_id
        return initial

    def form_valid(self, form):
        if self.request.user.is_customer:
            form.instance.customer = self.request.user
        if not self.save_booking(form):
            return self.form_invalid(form)
        messages.success(self.request, "Your booking has been requested. We'll confirm it shortly."
                         if self.request.user.is_customer else "The booking has been created.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Book a service"
        return context


class BookingUpdateView(BookingSaveMixin, BookingQuerysetMixin, UpdateView):
    context_object_name = "booking"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if (
            not self.request.user.is_customer
            and hasattr(self.object, "job_card")
        ):
            form.fields["open_invoice"] = forms.BooleanField(
                required=False,
                label="Open invoice after completing the service",
                help_text="When selected, save changes and open this job's invoice if service status is Completed.",
                widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
            )
        return form

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        if not booking.can_be_edited_by(self.request.user):
            raise PermissionDenied
        self.original_status = booking.status
        return booking

    def form_valid(self, form):
        open_invoice = form.cleaned_data.get("open_invoice", False)
        completes_service = form.cleaned_data.get("status") == "COMPLETED" and self.original_status != "COMPLETED"
        if not self.save_booking(form):
            return self.form_invalid(form)
        messages.success(self.request, "The booking has been updated.")
        if open_invoice and completes_service and hasattr(self.object, "job_card"):
            return redirect("jobcard_invoice", pk=self.object.job_card.pk)
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit booking"
        return context


class BookingCancelView(BookingQuerysetMixin, DetailView):
    """Asks for confirmation (GET) and then cancels the booking (POST). The booking is kept."""

    template_name = "bookings/booking_confirm_cancel.html"
    context_object_name = "booking"

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        if not booking.can_be_cancelled_by(self.request.user):
            raise PermissionDenied
        return booking

    def post(self, request, *args, **kwargs):
        booking = self.get_object()
        booking.status = "CANCELLED"
        booking.save(update_fields=["status"])
        messages.success(request, "The booking has been cancelled.")
        return redirect("booking_list")


class BookingDeleteView(AdminRequiredMixin, DeleteView):
    """Permanently removes a booking. Admins only; customers cancel instead."""

    model = Booking
    template_name = "bookings/booking_confirm_delete.html"
    context_object_name = "booking"
    success_url = reverse_lazy("booking_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "The booking has been deleted.")
        return response
