from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('signup/done/', views.SignUpDoneView.as_view(), name='signup_done'),
    path('verify/resend/', views.ResendVerificationView.as_view(), name='resend_verification'),
    path('verify/<uidb64>/<token>/', views.verify_email, name='verify_email'),
    path('login/', views.UserLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),  # POST only
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('password-reset/', views.UserPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.UserPasswordResetDoneView.as_view(), name='password_reset_done'),
    path(
        'password-reset/confirm/<uidb64>/<token>/',
        views.UserPasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path('password-reset/complete/', views.UserPasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
