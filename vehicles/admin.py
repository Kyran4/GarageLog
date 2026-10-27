from django.contrib import admin

from .models import Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate', 'make', 'model', 'year', 'owner', 'wof_expiry', 'rego_expiry')
    list_filter = ('make',)
    search_fields = ('plate', 'make', 'model', 'owner__username', 'owner__email')
