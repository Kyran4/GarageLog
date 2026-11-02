from django.views.generic import ListView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User

from .models import JobCard


class JobCardListView(RoleRequiredMixin, ListView):
    """Mechanics see the job cards assigned to them. Admins see all job cards."""

    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)
    template_name = "jobs/jobcard_list.html"
    context_object_name = "job_cards"

    def get_queryset(self):
        job_cards = JobCard.objects.select_related(
            "booking", "booking__vehicle", "mechanic"
        ).order_by("-created_at")

        user = self.request.user
        if user.is_admin_role:
            return job_cards
        return job_cards.filter(mechanic=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "All job cards" if self.request.user.is_admin_role else "My job cards"
        return context