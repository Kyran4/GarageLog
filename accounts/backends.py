from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

UserModel = get_user_model()


def get_user_by_login(identifier):
    """Find a user by username or email (case-insensitive). Exact username wins."""
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    manager = UserModel._default_manager
    user = manager.filter(username__iexact=identifier).order_by('pk').first()
    if user is None:
        user = manager.filter(email__iexact=identifier).order_by('pk').first()
    return user


class EmailOrUsernameBackend(ModelBackend):
    """Let users log in with either their username or their email address.

    Inactive users are still rejected here (via user_can_authenticate); the login
    form looks them up separately to show a helpful message.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        user = get_user_by_login(username)
        if user is None:
            # Run the hasher anyway so timing does not reveal which accounts exist.
            UserModel().set_password(password)
            return None
        if (
            user.check_password(password)
            and user.is_approved
            and self.user_can_authenticate(user)
        ):
            return user
        return None

    def user_can_authenticate(self, user):
        return user.is_approved and super().user_can_authenticate(user)
