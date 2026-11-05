from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.mixins import (
    AdminRequiredMixin,
    CustomerRequiredMixin,
    MechanicRequiredMixin,
    RoleRequiredMixin,
)
from bookings.models import Booking
from inventory.models import Part, StockItem
from jobs.models import JobCard, JobPart
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
        context['pending_count'] = Booking.objects.filter(
            workshop_id=user.workshop_id,
            status='PENDING',
        ).count() if user.workshop_id and not is_warehouse else 0
        context['overdue_job_count'] = JobCard.objects.filter(
            mechanic=user,
            booking__booking_date__lt=timezone.localdate(),
            booking__status__in=('CONFIRMED', 'IN_PROGRESS'),
        ).count()
        context['pending_url'] = reverse('booking_list') + '?status=PENDING'
        context['overdue_jobs_url'] = reverse('jobcard_list') + '?overdue=1'
        context['booking_count'] = Booking.objects.filter(workshop_id=user.workshop_id).count() \
            if user.workshop_id else 0
        context['analytics_url'] = reverse('analytics')
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
        context['overdue_job_count'] = JobCard.objects.filter(
            booking__booking_date__lt=timezone.localdate(),
            booking__status__in=('CONFIRMED', 'IN_PROGRESS'),
        ).count()
        context['overdue_jobs_url'] = reverse('jobcard_list') + '?overdue=1'
        context['low_stock_rows'] = [
            {
                'workshop_name': row['workshop__name'],
                'count': row['item_count'],
                'url': reverse('inventory:stock') + f"?workshop={row['workshop_id']}&low=1",
            }
            for row in StockItem.objects.filter(
                quantity__lte=F('reorder_level'),
            ).values('workshop_id', 'workshop__name').annotate(
                item_count=Count('pk'),
            ).order_by('workshop__name')
        ]
        context['low_stock_count'] = sum(row['count'] for row in context['low_stock_rows'])
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
        context['booking_count'] = Booking.objects.count()
        context['analytics_url'] = reverse('analytics')
        return context


class AnalyticsView(RoleRequiredMixin, TemplateView):
    allowed_roles = (User.Role.ADMIN, User.Role.MECHANIC)
    template_name = 'dashboard/analytics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        is_admin = user.is_admin_role

        bookings = Booking.objects.all()
        if not is_admin:
            bookings = bookings.filter(workshop_id=user.workshop_id)

        status_counts = dict(
            bookings.values('status').annotate(count=Count('pk')).values_list('status', 'count')
        )
        context['booking_count'] = bookings.count()
        context['status_rows'] = [
            {'label': label, 'count': status_counts.get(value, 0)}
            for value, label in Booking.STATUS_CHOICES
        ]
        context['service_rows'] = list(
            bookings.values('service_type')
            .annotate(count=Count('pk'))
            .order_by('-count', 'service_type')
        )

        completed_jobs = JobCard.objects.filter(booking__status='COMPLETED')
        completed_parts = JobPart.objects.filter(job_card__booking__status='COMPLETED')
        if not is_admin:
            completed_jobs = completed_jobs.filter(booking__workshop_id=user.workshop_id)
            completed_parts = completed_parts.filter(
                job_card__booking__workshop_id=user.workshop_id,
            )

        labor_total = completed_jobs.aggregate(total=Sum('labor_charge'))['total'] or Decimal('0.00')
        parts_total = completed_parts.aggregate(
            total=Sum(ExpressionWrapper(
                F('unit_price') * F('quantity') + F('freight_charge'),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ))
        )['total'] or Decimal('0.00')
        revenue = labor_total + parts_total
        completed_job_count = completed_jobs.count()
        context['completed_job_count'] = completed_job_count
        context['revenue'] = revenue
        context['average_invoice'] = (
            revenue / completed_job_count if completed_job_count else Decimal('0.00')
        )
        context['workshop'] = user.workshop if not is_admin else None
        context['is_admin_analytics'] = is_admin

        if is_admin:
            workshop_bookings = {
                row['workshop_id']: row
                for row in bookings.values('workshop_id').annotate(
                    booking_count=Count('pk'),
                    completed_count=Count('pk', filter=Q(status='COMPLETED')),
                )
            }
            workshop_labor = dict(
                JobCard.objects.filter(booking__status='COMPLETED')
                .values_list('booking__workshop_id')
                .annotate(total=Sum('labor_charge'))
                .values_list('booking__workshop_id', 'total')
            )
            workshop_parts = dict(
                JobPart.objects.filter(job_card__booking__status='COMPLETED')
                .values_list('job_card__booking__workshop_id')
                .annotate(total=Sum(ExpressionWrapper(
                    F('unit_price') * F('quantity') + F('freight_charge'),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )))
                .values_list('job_card__booking__workshop_id', 'total')
            )
            context['workshop_rows'] = [
                {
                    'workshop': workshop,
                    'booking_count': workshop_bookings.get(workshop.pk, {}).get('booking_count', 0),
                    'completed_count': workshop_bookings.get(workshop.pk, {}).get('completed_count', 0),
                    'revenue': (
                        workshop_labor.get(workshop.pk) or Decimal('0.00')
                    ) + (
                        workshop_parts.get(workshop.pk) or Decimal('0.00')
                    ),
                }
                for workshop in Workshop.objects.filter(is_parts_warehouse=False).order_by('name')
            ]
        return context
