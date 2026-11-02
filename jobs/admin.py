from django.contrib import admin
from .models import JobCard


@admin.register(JobCard)
class JobCardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "booking",
        "mechanic",
        "status",
        "created_at",
    )

    list_filter = ("status", "created_at")

    search_fields = (
        "booking__service_type",
        "mechanic__username",
    )
