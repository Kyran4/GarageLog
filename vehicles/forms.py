from django import forms
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.models import User

from .models import Vehicle, normalize_plate

MAX_YEARS_AHEAD = 5


class OwnerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.get_full_name() or obj.username} ({obj.username})'


class VehicleForm(BootstrapFormMixin, forms.ModelForm):
    # Only admins get to pick the owner; for customers this field is removed in __init__.
    owner = OwnerChoiceField(
        queryset=User.objects.filter(role=User.Role.CUSTOMER, is_active=True).order_by('username'),
        label='Owner',
        empty_label='Select a customer',
    )

    class Meta:
        model = Vehicle
        fields = ['owner', 'plate', 'make', 'model', 'year', 'wof_expiry', 'rego_expiry']
        widgets = {
            'plate': forms.TextInput(attrs={'autocapitalize': 'characters', 'autocomplete': 'off'}),
            'wof_expiry': forms.DateInput(attrs={'type': 'date'}),
            'rego_expiry': forms.DateInput(attrs={'type': 'date'}),
        }
        help_texts = {
            'plate': 'Letters and numbers only, for example ABC123.',
            'wof_expiry': 'Optional. We use this to remind you before it runs out.',
            'rego_expiry': 'Optional. We use this to remind you before it runs out.',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is None or not user.is_admin_role:
            del self.fields['owner']

    def save(self, commit=True):
        vehicle = super().save(commit=False)
        if vehicle.owner_id is None:
            vehicle.owner = self.user  # customers always own what they add
        if commit:
            vehicle.save()
        return vehicle

    def clean_plate(self):
        plate = normalize_plate(self.cleaned_data['plate'])
        clashes = Vehicle.objects.filter(plate=plate).exclude(pk=self.instance.pk)
        if clashes.exists():
            raise forms.ValidationError('A vehicle with this number plate is already registered.')
        return plate

    def _check_expiry(self, name):
        value = self.cleaned_data.get(name)
        if value and value.year > timezone.localdate().year + MAX_YEARS_AHEAD:
            raise forms.ValidationError(f'That date is more than {MAX_YEARS_AHEAD} years away. Please check it.')
        return value

    def clean_wof_expiry(self):
        return self._check_expiry('wof_expiry')

    def clean_rego_expiry(self):
        return self._check_expiry('rego_expiry')
