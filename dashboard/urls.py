from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard_redirect, name='dashboard'),
    path('dashboard/customer/', views.CustomerDashboardView.as_view(), name='customer_dashboard'),
    path('dashboard/mechanic/', views.MechanicDashboardView.as_view(), name='mechanic_dashboard'),
    path('dashboard/admin/', views.AdminDashboardView.as_view(), name='admin_dashboard'),
    path('dashboard/analytics/', views.AnalyticsView.as_view(), name='analytics'),
]
