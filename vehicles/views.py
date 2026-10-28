from django.contrib import messages
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from bookings.models import Booking

from .forms import VehicleForm
from .models import Vehicle, normalize_plate


class VehicleAccessMixin(RoleRequiredMixin):
    """Who can look at vehicles.

    Customers see their own vehicles. Mechanics and admins can look up any vehicle that is in
    the system (mechanics by searching for a plate) and read its service history. Changing
    vehicles is limited to owners and admins (see VehicleWriteMixin).
    """

    allowed_roles = (User.Role.CUSTOMER, User.Role.MECHANIC, User.Role.ADMIN)

    def get_queryset(self):
        vehicles = Vehicle.objects.select_related('owner')
        user = self.request.user
        if user.is_admin_role or user.is_mechanic:
            return vehicles
        # Someone else's vehicle simply does not exist as far as a customer can tell (404).
        return vehicles.filter(owner=user)


class VehicleWriteMixin(VehicleAccessMixin):
    """Adding, editing and deleting is for owners (customers) and admins only."""

    allowed_roles = (User.Role.CUSTOMER, User.Role.ADMIN)


class VehicleListView(VehicleAccessMixin, ListView):
    template_name = 'vehicles/vehicle_list.html'
    context_object_name = 'vehicles'
    paginate_by = 20

    def get_search_text(self):
        return normalize_plate(self.request.GET.get('q', ''))

    def get_queryset(self):
        vehicles = super().get_queryset()
        search = self.get_search_text()
        if self.request.user.is_mechanic:
            # Mechanics find a vehicle by plate rather than browsing every customer's vehicles.
            return vehicles.filter(plate__contains=search) if len(search) >= 2 else vehicles.none()
        return vehicles.filter(plate__contains=search) if search else vehicles

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['is_mechanic'] = user.is_mechanic
        context['can_search'] = user.is_mechanic or user.is_admin_role
        context['can_add'] = not user.is_mechanic
        context['search_text'] = self.request.GET.get('q', '').strip()
        context['needs_search'] = user.is_mechanic and len(self.get_search_text()) < 2
        return context


class VehicleDetailView(VehicleAccessMixin, DetailView):
    template_name = 'vehicles/vehicle_detail.html'
    context_object_name = 'vehicle'

    def _can_open_booking(self, booking):
        user = self.request.user
        if user.is_admin_role:
            return True
        if user.is_mechanic:
            return booking.workshop_id == user.workshop_id
        return booking.customer_id == user.pk

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        vehicle = self.object
        is_owner = vehicle.owner_id == user.pk

        # Service history timeline: every booking for this vehicle at any workshop, newest first.
        history = list(
            vehicle.bookings.select_related('workshop', 'mechanic').order_by('-booking_date', '-booking_time')
        )
        for booking in history:
            booking.can_open = self._can_open_booking(booking)
        context['history'] = history

        context['can_edit'] = user.is_admin_role or is_owner
        context['is_staff_view'] = user.is_mechanic or user.is_admin_role
        # A mechanic sees a customer's contact details only once that customer has booked at their workshop.
        context['can_see_contact'] = (
            user.is_admin_role
            or is_owner
            or (
                user.is_mechanic
                and Booking.objects.filter(customer_id=vehicle.owner_id, workshop_id=user.workshop_id).exists()
            )
        )
        return context


class VehicleFormMixin(VehicleWriteMixin):
    form_class = VehicleForm
    template_name = 'vehicles/vehicle_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse('vehicles:detail', kwargs={'pk': self.object.pk})


class VehicleCreateView(VehicleFormMixin, CreateView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'{self.object.plate} has been added.')
        return response


class VehicleUpdateView(VehicleFormMixin, UpdateView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'{self.object.plate} has been updated.')
        return response


class VehicleDeleteView(VehicleWriteMixin, DeleteView):
    template_name = 'vehicles/vehicle_confirm_delete.html'
    context_object_name = 'vehicle'
    success_url = reverse_lazy('vehicles:list')

    def form_valid(self, form):
        plate = self.object.plate
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f'{plate} has bookings, so it cannot be deleted. Its service history needs to be kept.',
            )
            return redirect('vehicles:detail', pk=self.object.pk)
        messages.success(self.request, f'{plate} has been deleted.')
        return response
