from django.urls import path

from . import views

app_name = 'vehicles'

urlpatterns = [
    path('', views.VehicleListView.as_view(), name='list'),
    path('add/', views.VehicleCreateView.as_view(), name='create'),
    path('<int:pk>/', views.VehicleDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.VehicleUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.VehicleDeleteView.as_view(), name='delete'),
]
