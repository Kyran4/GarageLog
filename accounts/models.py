from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models


class UserManager(DjangoUserManager):
    """Superusers made with `createsuperuser` get the ADMIN role and a verified email."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'ADMIN')
        extra_fields.setdefault('email_verified', True)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        MECHANIC = 'MECHANIC', 'Mechanic'
        ADMIN = 'ADMIN', 'Admin'

    email = models.EmailField('email address', unique=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    phone = models.CharField(max_length=30, blank=True)
    email_verified = models.BooleanField(default=False)
    workshop = models.ForeignKey(
        'workshops.Workshop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff',
        help_text='The workshop a mechanic works at. Mechanics can only manage bookings for this workshop.',
    )

    objects = UserManager()

    def clean(self):
        super().clean()
        if self.role == self.Role.MECHANIC and not self.workshop_id:
            raise ValidationError({'workshop': 'Choose the workshop this mechanic works at.'})

    def save(self, *args, **kwargs):
        # Keep emails lower-case so uniqueness is effectively case-insensitive.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def effective_role(self):
        """Django superusers are always treated as admins."""
        return self.Role.ADMIN if self.is_superuser else self.role

    def has_role(self, *roles):
        return self.effective_role in roles

    @property
    def is_customer(self):
        return self.has_role(self.Role.CUSTOMER)

    @property
    def is_mechanic(self):
        return self.has_role(self.Role.MECHANIC)

    @property
    def is_admin_role(self):
        return self.has_role(self.Role.ADMIN)
