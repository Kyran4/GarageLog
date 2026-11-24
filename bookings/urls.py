
from django.urls import path
from . import views

urlpatterns = [
    path("", views.BookingListView.as_view(), name="booking_list"),
    path("create/", views.BookingCreateView.as_view(), name="create_booking"),
    path("<int:pk>/", views.BookingDetailView.as_view(), name="booking_detail"),
    path("<int:pk>/edit/", views.BookingUpdateView.as_view(), name="booking_edit"),
    path("<int:pk>/cancel/", views.BookingCancelView.as_view(), name="booking_cancel"),
    path("<int:offer_pk>/earlier-slot/accept/", views.EarlierSlotOfferAcceptView.as_view(), name="booking_earlier_slot_accept"),
    path("<int:offer_pk>/earlier-slot/decline/", views.EarlierSlotOfferDeclineView.as_view(), name="booking_earlier_slot_decline"),
    path("<int:pk>/quote/", views.BookingQuoteView.as_view(), name="booking_quote"),
    path("<int:pk>/accept-quote/", views.BookingAcceptQuoteView.as_view(), name="booking_accept_quote"),
    path("<int:pk>/decline-quote/", views.BookingDeclineQuoteView.as_view(), name="booking_decline_quote"),
    path("<int:pk>/repeat/", views.BookingRepeatView.as_view(), name="booking_repeat"),
    path("<int:pk>/dropoff-checkin/", views.BookingDropoffCheckinView.as_view(), name="booking_dropoff_checkin"),
    path("<int:pk>/courtesy-assign/", views.BookingCourtesyAssignView.as_view(), name="booking_courtesy_assign"),
    # Short aliases make the quoting actions easy to link from integrations.
    path("<int:pk>/submit-quote/", views.BookingQuoteView.as_view(), name="booking_submit_quote"),
    path("<int:pk>/delete/", views.BookingDeleteView.as_view(), name="booking_delete"),
]
