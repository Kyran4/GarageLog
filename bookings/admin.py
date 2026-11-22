from django.contrib import admin

from .models import (
    Booking,
    BookingQuoteLabour,
    BookingQuotePart,
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


@admin.register(ServiceLabourRecommendation)
class ServiceLabourRecommendationAdmin(admin.ModelAdmin):
    list_display = ('service_type', 'recommended_charge', 'updated_at')
    list_editable = ('recommended_charge',)
    search_fields = ('service_type',)
    ordering = ('service_type',)
