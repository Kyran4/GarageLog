from .models import Booking
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from .forms import BookingForm


@login_required
def create_booking(request):

	if request.method == "POST":
		form = BookingForm(request.POST)

		if form.is_valid():
			booking = form.save(commit=False)
			booking.customer = request.user
			booking.save()

			return redirect("booking_list")

	else:
		form = BookingForm()

	return render(request, "bookings/create_booking.html", {"form": form})

@login_required
def booking_list(request):
    bookings = Booking.objects.filter(
        customer=request.user
    ).order_by("-booking_date", "-booking_time")

    return render(
        request,
        "bookings/booking_list.html",
        {"bookings": bookings}
    )