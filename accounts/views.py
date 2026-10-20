from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.generic import FormView, TemplateView, UpdateView

from .emails import send_verification_email
from .forms import (
    LoginForm,
    ProfileForm,
    ResendVerificationForm,
    SignUpForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
)
from .models import User
from .tokens import email_verification_token


class SignUpView(FormView):
    template_name = 'accounts/signup.html'
    form_class = SignUpForm
    success_url = reverse_lazy('accounts:signup_done')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        if not send_verification_email(self.request, user):
            messages.warning(
                self.request,
                'Your account was created, but we could not send the verification email. '
                'Use "Resend verification email" to try again.',
            )
        return super().form_valid(form)


class SignUpDoneView(TemplateView):
    template_name = 'accounts/signup_done.html'


def verify_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and email_verification_token.check_token(user, token):
        user.email_verified = True
        user.is_active = True
        user.save(update_fields=['email_verified', 'is_active'])
        messages.success(request, 'Your email address is verified. You can now log in.')
        return redirect('accounts:login')

    if user is not None and user.email_verified and user.is_active:
        messages.info(request, 'This email address is already verified. Please log in.')
        return redirect('accounts:login')

    return render(request, 'accounts/verify_invalid.html', status=400)


class ResendVerificationView(FormView):
    template_name = 'accounts/resend_verification.html'
    form_class = ResendVerificationForm
    success_url = reverse_lazy('accounts:login')

    def form_valid(self, form):
        user = User.objects.filter(email__iexact=form.cleaned_data['email']).first()
        # Only unverified accounts get a new link, but the reply is always the same
        # so this page cannot be used to find out which emails are registered.
        if user is not None and not user.email_verified:
            send_verification_email(self.request, user)
        messages.info(
            self.request,
            'If that email address belongs to an unverified account, we have sent a new verification link.',
        )
        return super().form_valid(form)


class UserLoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Welcome back, {form.get_user().first_name or form.get_user().username}.')
        return response


class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = 'accounts/profile.html'
    form_class = ProfileForm
    success_url = reverse_lazy('accounts:profile')

    def get_object(self, queryset=None):
        # Always the logged-in user, so nobody can edit another profile.
        return self.request.user

    def form_valid(self, form):
        user = form.save(commit=False)
        email_changed = 'email' in form.changed_data
        if email_changed:
            user.email_verified = False
        user.save()
        if email_changed:
            send_verification_email(self.request, user)
            messages.success(
                self.request,
                'Profile updated. We sent a verification link to your new email address.',
            )
        else:
            messages.success(self.request, 'Your profile has been updated.')
        return redirect(self.get_success_url())


class UserPasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    form_class = StyledPasswordResetForm
    email_template_name = 'accounts/email/password_reset_email.txt'
    subject_template_name = 'accounts/email/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')


class UserPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class UserPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy('accounts:password_reset_complete')


class UserPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'
