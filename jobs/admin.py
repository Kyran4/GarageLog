from django.contrib import admin
from .models import JobCard, JobPart, SupplierOrder


class JobPartInline(admin.TabularInline):
    model = JobPart
    extra = 0
    readonly_fields = (
        "part",
        "stock_item",
        "source",
        "name",
        "quantity",
        "unit_cost",
        "unit_price",
        "freight_charge",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(JobCard)
class JobCardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "booking",
        "mechanic",
        "booking_status",
        "created_at",
    )
    inlines = [JobPartInline]

    list_filter = ("booking__status", "created_at")

    search_fields = (
        "booking__service_type",
        "mechanic__username",
    )

    @admin.display(description="Service status", ordering="booking__status")
    def booking_status(self, obj):
        return obj.booking.get_status_display()


@admin.register(SupplierOrder)
class SupplierOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "part", "quantity", "job_part", "supplier", "supplier_reference", "ordered_by", "ordered_at", "received_at")
    list_filter = ("ordered_at", "received_at")
    search_fields = ("supplier", "supplier_reference", "part__name", "part__part_number", "job_part__name")
    readonly_fields = ("job_part", "ordered_by", "received_by", "ordered_at", "received_at")
