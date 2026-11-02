from django.urls import path

from . import views

urlpatterns = [
    path("", views.JobCardListView.as_view(), name="jobcard_list"),
    path("create/<int:booking_id>/", views.JobCardCreateView.as_view(), name="jobcard_create"),
    path("<int:pk>/", views.JobCardDetailView.as_view(), name="jobcard_detail"),
]