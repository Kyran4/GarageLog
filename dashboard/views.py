from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render
from django.views.generic import ListView, TemplateView

from accounts.mixins import AdminRequiredMixin, CustomerRequiredMixin, MechanicRequiredMixin

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


class CustomerDashboardView(CustomerRequiredMixin, TemplateView):
    template_name = 'dashboard/customer.html'


class MechanicDashboardView(MechanicRequiredMixin, TemplateView):
    template_name = 'dashboard/mechanic.html'


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
        return context
