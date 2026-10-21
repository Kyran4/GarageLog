from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from .models import User


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to users with one of `allowed_roles`.

    Logged-out users are sent to the login page; logged-in users with the
    wrong role get a 403 page.
    """

    allowed_roles = ()

    def test_func(self):
        return self.request.user.has_role(*self.allowed_roles)


class CustomerRequiredMixin(RoleRequiredMixin):
    allowed_roles = (User.Role.CUSTOMER,)


class MechanicRequiredMixin(RoleRequiredMixin):
    allowed_roles = (User.Role.MECHANIC,)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = (User.Role.ADMIN,)
