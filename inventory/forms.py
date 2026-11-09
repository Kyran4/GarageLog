from django import forms
from django.db.models import F

from accounts.forms import BootstrapFormMixin
from vehicles.models import Vehicle, normalize_plate
from workshops.models import Workshop

from .models import Part, PartFitment, StockItem


class StockLocationField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} (parts warehouse)' if obj.is_parts_warehouse else obj.name


class PartSearchForm(BootstrapFormMixin, forms.Form):
    """Find parts by vehicle (plate, or make and model) and/or by name, category and stock."""

    plate = forms.CharField(
        required=False, label='Number plate',
        help_text='A vehicle already in GarageLog. Its make, model and year are used to find matching parts.',
        widget=forms.TextInput(attrs={'autocapitalize': 'characters', 'autocomplete': 'off'}),
    )
    make = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'list': 'make-options', 'autocomplete': 'off'}),
    )
    model = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'list': 'model-options', 'autocomplete': 'off'}),
    )
    year = forms.IntegerField(required=False, min_value=1900, max_value=2100)
    q = forms.CharField(required=False, label='Part name or number')
    category = forms.ChoiceField(
        required=False, label='Category', choices=[('', 'All categories')] + Part.Category.choices,
    )
    in_stock = forms.BooleanField(required=False, label='Only parts in stock')
    workshop = StockLocationField(
        queryset=Workshop.objects.all(), required=False, empty_label=None, label='Workshop stock to show',
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle = None
        if user is None or not user.is_admin_role:
            del self.fields['workshop']  # a mechanic always sees their own workshop's stock

    def clean_plate(self):
        plate = normalize_plate(self.cleaned_data['plate'])
        if not plate:
            return ''
        self.vehicle = Vehicle.objects.filter(plate=plate).first()
        if self.vehicle is None:
            raise forms.ValidationError(
                "That plate isn't in GarageLog. Search by make and model instead."
            )
        return plate


class StockItemForm(BootstrapFormMixin, forms.ModelForm):
    """Add a catalogue part to a workshop's stock (part chosen), or change how much is held."""

    class Meta:
        model = StockItem
        fields = ['part', 'quantity', 'reorder_level', 'unit_price', 'bin_location']
        widgets = {'quantity': forms.NumberInput(attrs={'min': 0}), 'reorder_level': forms.NumberInput(attrs={'min': 0})}

    def __init__(self, *args, workshop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workshop = workshop
        if self.instance.pk:
            del self.fields['part']  # the part is fixed once it is in stock
        else:
            already = StockItem.objects.filter(workshop=workshop).values_list('part_id', flat=True)
            self.fields['part'].queryset = Part.objects.filter(is_active=True).exclude(pk__in=already)
            self.fields['part'].empty_label = 'Select a part'
            self.fields['part'].label_from_instance = lambda part: f'{part.part_number} - {part.name}'


class WarehouseStockTransferForm(BootstrapFormMixin, forms.Form):
    workshop = StockLocationField(
        queryset=Workshop.objects.none(),
        label='Destination workshop',
        empty_label='Select a workshop',
    )
    part = forms.ModelChoiceField(
        queryset=Part.objects.none(),
        label='Part',
        empty_label='Select a part',
    )
    quantity = forms.IntegerField(min_value=1, initial=1)

    def __init__(self, *args, warehouse=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.warehouse = warehouse
        self.fields['workshop'].queryset = Workshop.objects.filter(
            is_active=True,
            is_parts_warehouse=False,
        )
        if warehouse is not None:
            self.fields['part'].queryset = Part.objects.filter(
                is_active=True,
                stock_items__workshop=warehouse,
                stock_items__quantity__gt=0,
            ).annotate(
                warehouse_quantity=F('stock_items__quantity'),
            ).distinct()
            self.fields['part'].label_from_instance = (
                lambda part: f'{part.part_number} - {part.name} (available: {part.warehouse_quantity})'
            )

    def clean(self):
        cleaned_data = super().clean()
        part = cleaned_data.get('part')
        quantity = cleaned_data.get('quantity')
        if part is not None and quantity is not None and self.warehouse is not None:
            available = StockItem.objects.filter(
                workshop=self.warehouse,
                part=part,
            ).values_list('quantity', flat=True).first() or 0
            if quantity > available:
                self.add_error('quantity', f'Only {available} are available in the parts warehouse.')
        return cleaned_data
