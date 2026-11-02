from django.urls import path

from . import views

urlpatterns = [
    path("", views.JobCardListView.as_view(), name="jobcard_list"),
]