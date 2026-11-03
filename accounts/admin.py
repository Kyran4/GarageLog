from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        'username', 'email', 'first_name', 'last_name', 'role', 'workshop',
        'is_active',
    )
    list_filter = DjangoUserAdmin.list_filter + ('role', 'workshop')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('GarageLog', {'fields': ('role', 'workshop', 'phone')}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('GarageLog', {'fields': ('email', 'role', 'workshop', 'phone')}),
    )
