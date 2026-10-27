from django.contrib import messages
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User

from .forms import VehicleForm
from .models import Vehicle


class VehicleAccessMixin(RoleRequiredMixin):
    """Customers manage their own vehicles; admins manage all of them. Mechanics have no access."""

    allowed_roles = (User.Role.CUSTOMER, User.Role.ADMIN)

    def get_queryset(self):
        vehicles = Vehicle.objects.select_related('owner')
        if self.request.user.is_admin_role:
            return vehicles
        # Someone else's vehicle simply does not exist as far as a customer can tell (404).
        return vehicles.filter(owner=self.request.user)


class VehicleListView(VehicleAccessMixin, ListView):
    template_name = 'vehicles/vehicle_list.html'
    context_object_name = 'vehicles'
    paginate_by = 20


class VehicleDetailView(VehicleAccessMixin, DetailView):
    template_name = 'vehicles/vehicle_detail.html'
    context_object_name = 'vehicle'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Service history timeline: every booking for this vehicle, newest first.
        context['history'] = self.object.bookings.select_related('mechanic').order_by(
            '-booking_date', '-booking_time',
        )
        return context


class VehicleFormMixin(VehicleAccessMixin):
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


class VehicleDeleteView(VehicleAccessMixin, DeleteView):
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
