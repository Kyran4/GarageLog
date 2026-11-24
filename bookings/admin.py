from django.contrib import admin

from .models import (
    Booking,
    BookingQuoteLabour,
    BookingQuotePart,
    CourtesyReservation,
    CourtesyVehicle,
    ServiceLabourRecommendation,
)


class BookingQuotePartInline(admin.TabularInline):
    model = BookingQuotePart
    extra = 0
    can_delete = False


class BookingQuoteLabourInline(admin.TabularInline):
    model = BookingQuoteLabour
    extra = 0
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking_date', 'booking_time', 'service_type', 'vehicle', 'customer', 'mechanic', 'status')
    list_filter = ('status', 'booking_date')
    search_fields = ('service_type', 'vehicle__plate', 'customer__username', 'customer__email')
    inlines = [BookingQuotePartInline, BookingQuoteLabourInline]


@admin.register(CourtesyVehicle)
class CourtesyVehicleAdmin(admin.ModelAdmin):
    list_display = ("plate", "make", "model", "workshop", "is_active")
    list_filter = ("workshop", "is_active")
    search_fields = ("plate", "make", "model")


@admin.register(CourtesyReservation)
class CourtesyReservationAdmin(admin.ModelAdmin):
    list_display = ("booking", "vehicle", "start_date", "end_date", "status")
    list_filter = ("status", "start_date")


@admin.register(ServiceLabourRecommendation)
class ServiceLabourRecommendationAdmin(admin.ModelAdmin):
    list_display = ('service_type', 'recommended_charge', 'updated_at')
    list_editable = ('recommended_charge',)
    search_fields = ('service_type',)
    ordering = ('service_type',)
