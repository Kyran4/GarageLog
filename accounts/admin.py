from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    actions = ('approve_users',)
    list_display = (
        'username', 'email', 'first_name', 'last_name', 'role', 'workshop',
        'is_approved', 'is_active',
    )
    list_filter = DjangoUserAdmin.list_filter + ('role', 'workshop', 'is_approved')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('GarageLog', {'fields': ('role', 'workshop', 'phone', 'is_approved')}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('GarageLog', {'fields': ('email', 'role', 'workshop', 'phone', 'is_approved')}),
    )

    @admin.action(description='Approve selected users and activate their accounts')
    def approve_users(self, request, queryset):
        updated = queryset.update(is_approved=True, is_active=True)
        self.message_user(request, f'{updated} user account(s) approved and activated.')

    def save_model(self, request, obj, form, change):
        previous_approval = None
        if change:
            previous_approval = User.objects.filter(pk=obj.pk).values_list(
                'is_approved', flat=True,
            ).first()

        if not obj.is_approved:
            obj.is_active = False
        elif previous_approval is False or not change:
            obj.is_active = True
        super().save_model(request, obj, form, change)
