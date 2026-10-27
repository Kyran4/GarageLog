from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, TemplateView

from accounts.mixins import AdminRequiredMixin, CustomerRequiredMixin, MechanicRequiredMixin
from bookings.models import Booking
from vehicles.models import Vehicle

User = get_user_model()


def home(request):
    return render(request, 'home.html')


@login_required
def dashboard_redirect(request):
    """Send the user to the dashboard for their role."""
    user = request.user
    if user.is_admin_role:
        return redirect('admin_dashboard')
    if user.is_mechanic:
        return redirect('mechanic_dashboard')
    return redirect('customer_dashboard')


def upcoming_bookings(**filters):
    """Active bookings that have not happened yet, soonest first."""
    today = timezone.localdate()
    bookings = Booking.objects.filter(
        status__in=Booking.ACTIVE_STATUSES, booking_date__gte=today, **filters,
    ).select_related('vehicle').order_by('booking_date', 'booking_time')
    # Bookings earlier today whose time has passed are not upcoming any more.
    return [booking for booking in bookings if booking.is_upcoming]


class CustomerDashboardView(CustomerRequiredMixin, TemplateView):
    template_name = 'dashboard/customer.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        upcoming = upcoming_bookings(customer=user)
        vehicles = list(Vehicle.objects.filter(owner=user))
        context['vehicle_count'] = len(vehicles)
        context['upcoming_count'] = len(upcoming)
        context['next_bookings'] = upcoming[:3]
        context['expiring_vehicles'] = [
            vehicle for vehicle in vehicles
            if vehicle.wof_status in ('expired', 'soon') or vehicle.rego_status in ('expired', 'soon')
        ]
        context['vehicles_url'] = reverse('vehicles:list')
        context['bookings_url'] = reverse('booking_list')
        return context


class MechanicDashboardView(MechanicRequiredMixin, TemplateView):
    template_name = 'dashboard/mechanic.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        upcoming = upcoming_bookings(mechanic=self.request.user)
        context['upcoming_count'] = len(upcoming)
        context['next_bookings'] = upcoming[:5]
        context['bookings_url'] = reverse('booking_list')
        return context


class AdminDashboardView(AdminRequiredMixin, ListView):
    """Admin shell with a read-only list of users."""

    model = User
    template_name = 'dashboard/admin.html'
    context_object_name = 'users'
    paginate_by = 20
    ordering = ('-date_joined', '-pk')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = dict(User.objects.values_list('role').annotate(total=Count('pk')))
        context['total_users'] = sum(counts.values())
        context['customer_count'] = counts.get(User.Role.CUSTOMER, 0)
        context['mechanic_count'] = counts.get(User.Role.MECHANIC, 0)
        context['admin_count'] = counts.get(User.Role.ADMIN, 0)
        context['pending_count'] = Booking.objects.filter(status='PENDING').count()
        context['upcoming_count'] = len(upcoming_bookings())
        context['vehicle_count'] = Vehicle.objects.count()
        context['bookings_url'] = reverse('booking_list')
        context['pending_url'] = reverse('booking_list') + '?status=PENDING'
        context['vehicles_url'] = reverse('vehicles:list')
        return context
