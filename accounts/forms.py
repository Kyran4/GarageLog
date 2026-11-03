from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.core.exceptions import ValidationError

from .backends import get_user_by_login
from .models import User
from .validators import validate_phone


class BootstrapFormMixin:
    """Add Bootstrap classes to every widget, and mark invalid fields after validation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'form-check-input'
            elif isinstance(widget, forms.Select):
                css = 'form-select'
            else:
                css = 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css}".strip()

    def full_clean(self):
        super().full_clean()
        for name in self._errors or {}:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs['class'] = f"{widget.attrs.get('class', '')} is-invalid".strip()


def _clean_unique_email(raw_email, exclude_pk=None):
    email = (raw_email or '').strip().lower()
    clashes = User.objects.filter(email__iexact=email)
    if exclude_pk is not None:
        clashes = clashes.exclude(pk=exclude_pk)
    if clashes.exists():
        raise ValidationError('An account with this email address already exists.')
    return email


class SignUpForm(BootstrapFormMixin, UserCreationForm):
    email = forms.EmailField(
        label='Email address',
        help_text='An admin will review your account before you can log in.',
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )
    first_name = forms.CharField(
        label='First name', max_length=150,
        widget=forms.TextInput(attrs={'autocomplete': 'given-name'}),
    )
    last_name = forms.CharField(
        label='Last name', max_length=150,
        widget=forms.TextInput(attrs={'autocomplete': 'family-name'}),
    )
    phone = forms.CharField(
        label='Phone (optional)', max_length=30, required=False,
        validators=[validate_phone],
        widget=forms.TextInput(attrs={'autocomplete': 'tel', 'inputmode': 'tel'}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'phone')

    def clean_email(self):
        return _clean_unique_email(self.cleaned_data.get('email'))

    def save(self, commit=True):
        user = super().save(commit=False)
        # Role and status are never taken from the form.
        user.role = User.Role.CUSTOMER
        user.is_staff = False
        user.is_superuser = False
        user.is_active = False
        user.is_approved = False
        if commit:
            user.save()
            self.save_m2m()
        return user


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    username = forms.CharField(
        label='Username or email',
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}),
    )

    error_messages = {
        'invalid_login': 'The username/email or password is incorrect. Please check both and try again.',
        'inactive': 'This account has been disabled. Please contact the workshop for help.',
        'pending_approval': 'Your account is awaiting admin approval. Please try again later.',
    }

    def clean(self):
        identifier = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        if identifier is not None and password:
            self.user_cache = authenticate(self.request, username=identifier, password=password)
            if self.user_cache is None:
                # Only disclose account status when the password is correct.
                account = get_user_by_login(identifier)
                if account is not None and account.check_password(password):
                    if not account.is_approved:
                        code = 'pending_approval'
                    elif not account.is_active:
                        code = 'inactive'
                    else:
                        raise self.get_invalid_login_error()
                    raise ValidationError(self.error_messages[code], code=code)
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    first_name = forms.CharField(label='First name', max_length=150)
    last_name = forms.CharField(label='Last name', max_length=150)
    email = forms.EmailField(label='Email address')
    phone = forms.CharField(
        label='Phone (optional)', max_length=30, required=False,
        validators=[validate_phone],
        widget=forms.TextInput(attrs={'inputmode': 'tel'}),
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone')

    def clean_email(self):
        return _clean_unique_email(self.cleaned_data.get('email'), exclude_pk=self.instance.pk)


class ResendVerificationForm(BootstrapFormMixin, forms.Form):
    email = forms.EmailField(
        label='Email address',
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}),
    )


class StyledPasswordResetForm(BootstrapFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass
