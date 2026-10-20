import pytest

from accounts.models import User

PASSWORD = 'S3cure-Pass-Word!'


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """Real hashers are deliberately slow; use a fast one so the test suite stays quick."""
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def make_user(db):
    """Create a verified, active user. Override any field with keyword arguments."""

    def _make(username, role=User.Role.CUSTOMER, **extra):
        fields = {
            'email': f'{username}@example.com',
            'password': PASSWORD,
            'role': role,
            'is_active': True,
            'email_verified': True,
        }
        fields.update(extra)
        return User.objects.create_user(username=username, **fields)

    return _make


@pytest.fixture
def customer(make_user):
    return make_user('customer', User.Role.CUSTOMER, first_name='Casey')


@pytest.fixture
def mechanic(make_user):
    return make_user('mechanic', User.Role.MECHANIC)


@pytest.fixture
def admin_user(make_user):
    return make_user('adminuser', User.Role.ADMIN)
