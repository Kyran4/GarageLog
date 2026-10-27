from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking_date', 'booking_time', 'service_type', 'vehicle', 'customer', 'mechanic', 'status')
    list_filter = ('status', 'booking_date')
    search_fields = ('service_type', 'vehicle__plate', 'customer__username', 'customer__email')
