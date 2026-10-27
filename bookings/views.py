from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import AdminRequiredMixin, RoleRequiredMixin
from accounts.models import User
from vehicles.models import Vehicle

from . import scheduling
from .forms import AdminBookingForm, BookingForm
from .models import Booking


class BookingQuerysetMixin(LoginRequiredMixin):
    """Each role only ever sees its own slice of the bookings.

    Customers see their own bookings, mechanics see the ones assigned to them, and admins see
    everything. Anything outside that slice is a 404, so URLs cannot be guessed to read it.
    """

    def get_queryset(self):
        user = self.request.user
        bookings = Booking.objects.select_related("customer", "mechanic", "vehicle")
        if user.is_admin_role:
            return bookings
        if user.is_mechanic:
            return bookings.filter(mechanic=user)
        return bookings.filter(customer=user)


class BookingListView(BookingQuerysetMixin, ListView):
    template_name = "bookings/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 20

    def get_queryset(self):
        bookings = super().get_queryset().order_by("-booking_date", "-booking_time")
        status = self.request.GET.get("status", "")
        if self.request.user.is_admin_role and status in dict(Booking.STATUS_CHOICES):
            bookings = bookings.filter(status=status)
        return bookings

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["is_admin"] = user.is_admin_role
        context["is_mechanic"] = user.is_mechanic
        context["can_create"] = user.is_admin_role or user.is_customer
        context["page_title"] = (
            "All bookings" if user.is_admin_role
            else "Assigned bookings" if user.is_mechanic
            else "My bookings"
        )
        if user.is_admin_role:
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
        context["can_see_vehicle_page"] = user.is_admin_role or user.is_customer
        return context


class BookingSaveMixin:
    """Shared by the create and edit views: picks the form for the role and saves safely."""

    template_name = "bookings/create_booking.html"

    def get_form_class(self):
        return AdminBookingForm if self.request.user.is_admin_role else BookingForm

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
                scheduling.lock_capacity()
                if (
                    booking.status in Booking.ACTIVE_STATUSES
                    and scheduling.booked_count(booking.booking_date, booking.booking_time, booking.pk)
                    >= scheduling.capacity()
                ):
                    form.add_error("booking_time", "That time was just taken. Please choose another time.")
                    return False
                self.object = form.save()
        except IntegrityError:
            form.add_error(None, "That time was just taken by another booking. Please choose a different time.")
            return False
        return True


class BookingCreateView(BookingSaveMixin, RoleRequiredMixin, CreateView):
    allowed_roles = (User.Role.CUSTOMER, User.Role.ADMIN)

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and user.is_customer and not Vehicle.objects.filter(owner=user).exists():
            messages.info(request, "Add your vehicle first, then you can book a service for it.")
            return redirect("vehicles:create")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        vehicle_id = self.request.GET.get("vehicle")
        if vehicle_id and vehicle_id.isdigit():
            initial["vehicle"] = vehicle_id
            if self.request.user.is_admin_role:
                # Booking from a vehicle's page: start with that vehicle's owner selected.
                owner_id = Vehicle.objects.filter(pk=vehicle_id).values_list("owner_id", flat=True).first()
                if owner_id:
                    initial["customer"] = owner_id
        return initial

    def form_valid(self, form):
        if not self.request.user.is_admin_role:
            form.instance.customer = self.request.user
        if not self.save_booking(form):
            return self.form_invalid(form)
        messages.success(self.request, "Your booking has been requested. We'll confirm it shortly.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Book a service"
        return context


class BookingUpdateView(BookingSaveMixin, BookingQuerysetMixin, UpdateView):
    context_object_name = "booking"

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not (user.is_admin_role or user.is_customer):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        if not booking.can_be_edited_by(self.request.user):
            raise PermissionDenied
        return booking

    def form_valid(self, form):
        if not self.save_booking(form):
            return self.form_invalid(form)
        messages.success(self.request, "The booking has been updated.")
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
