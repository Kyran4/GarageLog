from decimal import Decimal
from django import forms
from django.db import transaction

from accounts.forms import BootstrapFormMixin
from bookings.models import Booking
from inventory.models import Part, StockItem
from workshops.models import Workshop

from .models import JobCard, JobPart, SupplierOrder


class JobCardForm(BootstrapFormMixin, forms.ModelForm):
    status = forms.ChoiceField(
        choices=Booking.STATUS_CHOICES,
        label="Service status",
    )
    open_invoice = forms.BooleanField(
        required=False,
        label="Open invoice after completing the service",
        help_text="When selected, save changes and open the invoice if service status is Completed.",
    )

    class Meta:
        model = JobCard
        fields = ["description", "work_done", "labor_charge"]

    field_order = ["status", "description", "work_done", "labor_charge", "open_invoice"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["status"].initial = self.instance.booking.status
        self.fields["labor_charge"].widget.attrs.update({"min": 0, "step": "0.01"})
        self.fields["description"].widget.attrs["rows"] = 3
        self.fields["work_done"].widget.attrs["rows"] = 5

    def save(self, commit=True):
        job_card = super().save(commit=False)
        if commit:
            with transaction.atomic():
                job_card.save()
                booking = job_card.booking
                booking.status = self.cleaned_data["status"]
                booking.save(update_fields=["status"])
            self.save_m2m()
        return job_card


class JobPartForm(BootstrapFormMixin, forms.ModelForm):
    part = forms.ModelChoiceField(
        queryset=Part.objects.none(),
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = JobPart
        fields = ["source", "part", "name", "quantity", "unit_cost", "unit_price", "freight_charge"]
        widgets = {
            "source": forms.HiddenInput(),
            "quantity": forms.NumberInput(attrs={"min": 1}),
            "unit_cost": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "freight_charge": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }
        help_texts = {
            "unit_cost": "Internal only. Customers see the customer unit price, not this cost.",
            "freight_charge": "Customer-visible freight per part; warehouse orders default to $12.99.",
        }

    def __init__(self, *args, workshop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workshop = workshop
        self.fields["part"].queryset = Part.objects.filter(is_active=True)
        self.fields["source"].choices = [
            (JobPart.Source.WORKSHOP, JobPart.Source.WORKSHOP.label),
            (JobPart.Source.WAREHOUSE, JobPart.Source.WAREHOUSE.label),
            (JobPart.Source.CATALOGUE, JobPart.Source.CATALOGUE.label),
            (JobPart.Source.MANUAL, JobPart.Source.MANUAL.label),
        ]
        self.fields["name"].label = "Part description"
        self.fields["name"].required = False
        self.fields["quantity"].min_value = 1
        self.fields["unit_cost"].required = False
        self.fields["unit_price"].required = False
        self.fields["freight_charge"].required = False
        self.fields["freight_charge"].initial = Decimal("0.00")

    def clean(self):
        cleaned = super().clean()
        part = cleaned.get("part")
        name = (cleaned.get("name") or "").strip()
        source = cleaned.get("source")
        cost = cleaned.get("unit_cost")
        price = cleaned.get("unit_price")
        freight = cleaned.get("freight_charge")

        if source == JobPart.Source.MANUAL:
            if part:
                self.add_error("part", "Choose a catalogue source or clear the selected catalogue part.")
            if not name:
                self.add_error("name", "Enter a description for a part that is not in the catalogue.")
            if cost is None:
                self.add_error("unit_cost", "Enter the cost to obtain this part.")
            if price is None:
                self.add_error("unit_price", "Enter the price to charge the customer.")
        elif part:
            quantity = cleaned.get("quantity") or 1
            workshop_stock = StockItem.objects.filter(
                workshop=self.workshop, part=part
            ).first() if self.workshop else None
            warehouse = Workshop.get_warehouse()
            warehouse_stock = StockItem.objects.filter(
                workshop=warehouse, part=part
            ).first() if warehouse else None
            source = (
                JobPart.Source.WORKSHOP
                if workshop_stock and workshop_stock.quantity >= quantity
                else JobPart.Source.WAREHOUSE
            )
            cleaned["source"] = source
            cleaned["name"] = part.name
            stock = workshop_stock if source == JobPart.Source.WORKSHOP else warehouse_stock
            default_price = stock.price if stock else part.default_price
            if price is None:
                cleaned["unit_price"] = default_price
            if source == JobPart.Source.WAREHOUSE:
                if freight is None:
                    cleaned["freight_charge"] = Decimal("12.99")
            else:
                cleaned["freight_charge"] = Decimal("0.00")
        else:
            self.add_error("part", "Search for and select a catalogue part, or choose Manual part.")
        return cleaned


class SupplierOrderForm(BootstrapFormMixin, forms.ModelForm):
    part = forms.ModelChoiceField(
        queryset=Part.objects.none(),
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = SupplierOrder
        fields = ["part", "quantity", "supplier", "supplier_reference", "unit_cost"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": 1}),
            "unit_cost": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }

    def __init__(self, *args, job_part=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["part"].queryset = Part.objects.filter(is_active=True)
        self.fields["part"].label_from_instance = lambda part: f"{part.part_number} - {part.name}"
        self.job_part = job_part
        if job_part:
            self.fields["part"].initial = job_part.part_id
            self.fields["part"].disabled = True
            self.fields["quantity"].initial = job_part.quantity
            self.fields["quantity"].disabled = True
