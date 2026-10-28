from django.contrib import admin

from .models import Workshop


@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'phone', 'open_time', 'close_time', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'address')
