from django.contrib import admin

from .models import Part, PartFitment, StockItem


class PartFitmentInline(admin.TabularInline):
    model = PartFitment
    extra = 1


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ('part_number', 'name', 'category', 'default_price', 'universal', 'is_active')
    list_filter = ('category', 'universal', 'is_active')
    search_fields = ('part_number', 'name', 'brand', 'fitments__make', 'fitments__model')
    inlines = [PartFitmentInline]


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ('part', 'workshop', 'quantity', 'reorder_level', 'unit_price', 'bin_location')
    list_filter = ('workshop',)
    search_fields = ('part__part_number', 'part__name')
    autocomplete_fields = ('part',)
