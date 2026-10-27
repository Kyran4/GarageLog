
from django.urls import path
from . import views

urlpatterns = [
    path("create/", views.create_booking, name="create_booking"),
    path("", views.booking_list, name="booking_list"),
    path("<int:booking_id>/edit/", views.edit_booking, name="edit_booking"),
    path("<int:booking_id>/cancel/", views.cancel_booking, name="cancel_booking"),
]
