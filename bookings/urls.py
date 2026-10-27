
from django.urls import path
from . import views

urlpatterns = [
    path("", views.BookingListView.as_view(), name="booking_list"),
    path("create/", views.BookingCreateView.as_view(), name="create_booking"),
    path("<int:pk>/", views.BookingDetailView.as_view(), name="booking_detail"),
    path("<int:pk>/edit/", views.BookingUpdateView.as_view(), name="booking_edit"),
    path("<int:pk>/cancel/", views.BookingCancelView.as_view(), name="booking_cancel"),
    path("<int:pk>/delete/", views.BookingDeleteView.as_view(), name="booking_delete"),
]
