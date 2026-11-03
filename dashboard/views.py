from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.mixins import AdminRequiredMixin, CustomerRequiredMixin, MechanicRequiredMixin
from bookings.models import Booking
from inventory.models import Part, StockItem
from vehicles.models import Vehicle
from workshops.models import Workshop

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
    ).select_related('vehicle', 'workshop', 'mechanic').order_by('booking_date', 'booking_time')
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
        user = self.request.user
        # A mechanic works with the bookings at their own workshop. The parts warehouse takes no bookings.
        is_warehouse = bool(user.workshop_id and user.workshop.is_parts_warehouse)
        upcoming = upcoming_bookings(workshop_id=user.workshop_id) if user.workshop_id and not is_warehouse else []
        context['workshop'] = user.workshop
        context['is_warehouse'] = is_warehouse
        context['upcoming_count'] = len(upcoming)
        context['assigned_count'] = len([booking for booking in upcoming if booking.mechanic_id == user.pk])
        context['next_bookings'] = upcoming[:5]
        context['bookings_url'] = reverse('booking_list')
        context['vehicles_url'] = reverse('vehicles:list')
        context['low_stock_count'] = StockItem.objects.filter(
            workshop_id=user.workshop_id, quantity__lte=F('reorder_level'),
        ).count() if user.workshop_id else 0
        context['parts_url'] = reverse('inventory:search')
        context['low_stock_url'] = reverse('inventory:stock') + '?low=1'
        return context


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    """Admin shell with read-only, role-specific user lists."""

    template_name = 'dashboard/admin.html'
    paginate_by = 20

    def get_user_page(self, queryset, page_parameter):
        queryset = queryset.select_related('workshop').order_by('-date_joined', '-pk')
        return Paginator(queryset, self.paginate_by).get_page(self.request.GET.get(page_parameter))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role_querysets = {
            'customers': User.objects.filter(role=User.Role.CUSTOMER, is_superuser=False),
            'mechanics': User.objects.filter(role=User.Role.MECHANIC, is_superuser=False),
            'admins': User.objects.filter(Q(role=User.Role.ADMIN) | Q(is_superuser=True)),
        }
        for name, queryset in role_querysets.items():
            page_parameter = f'{name}_page'
            page = self.get_user_page(queryset, page_parameter)
            context[name] = page
            context[f'{name}_page'] = page
            context[f'{name}_count'] = page.paginator.count

        context['total_users'] = User.objects.count()
        context['customer_count'] = context['customers_count']
        context['mechanic_count'] = context['mechanics_count']
        context['admin_count'] = context['admins_count']
        context['pending_count'] = Booking.objects.filter(status='PENDING').count()
        context['upcoming_count'] = len(upcoming_bookings())
        context['vehicle_count'] = Vehicle.objects.count()

        upcoming = upcoming_bookings()
        workshops = Workshop.objects.annotate(
            mechanic_count=Count('staff', filter=Q(staff__role=User.Role.MECHANIC, staff__is_active=True), distinct=True),
        )
        context['workshop_rows'] = [
            {
                'workshop': workshop,
                'mechanics': workshop.mechanic_count,
                'upcoming': len([booking for booking in upcoming if booking.workshop_id == workshop.pk]),
            }
            for workshop in workshops
        ]
        # The headline count is of workshops that take bookings; the parts warehouse is listed separately.
        context['workshop_count'] = len([row for row in context['workshop_rows'] if not row['workshop'].is_parts_warehouse])
        warehouse = Workshop.get_warehouse()
        context['warehouse'] = warehouse
        if warehouse:
            context['warehouse_stock_count'] = StockItem.objects.filter(workshop=warehouse).count()
            context['warehouse_stock_url'] = reverse('inventory:stock') + f'?workshop={warehouse.pk}'
        context['workshops_admin_url'] = reverse('admin:workshops_workshop_changelist')
        context['part_count'] = Part.objects.filter(is_active=True).count()
        context['parts_url'] = reverse('inventory:search')
        context['bookings_url'] = reverse('booking_list')
        context['pending_url'] = reverse('booking_list') + '?status=PENDING'
        context['vehicles_url'] = reverse('vehicles:list')
        return context
