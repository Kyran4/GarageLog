from django.contrib import admin

from .models import Workshop


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'phone', 'open_time', 'close_time', 'is_active', 'is_parts_warehouse')
    list_filter = ('is_active', 'is_parts_warehouse')
    search_fields = ('name', 'address')
