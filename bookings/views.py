from .models import Booking
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.contrib import messages

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
    ).exclude(
        status="CANCELLED"
    ).order_by("-booking_date", "-booking_time")

    return render(
        request,
        "bookings/booking_list.html",
        {"bookings": bookings}
    )


@login_required
def edit_booking(request, booking_id):
    booking = get_object_or_404(
        Booking,
        id=booking_id,
        customer=request.user
    )

    if booking.status in ["CANCELLED", "COMPLETED"]:
        return redirect("booking_list")

    if request.method == "POST":
        form = BookingForm(request.POST, instance=booking)

        if form.is_valid():
            form.save()
            return redirect("booking_list")
    else:
        form = BookingForm(instance=booking)

    return render(
        request,
        "bookings/edit_booking.html",
        {
            "form": form,
            "booking": booking
        }
    )

@login_required
@require_POST
def cancel_booking(request, booking_id):
    booking = get_object_or_404(
        Booking,
        id=booking_id,
        customer=request.user
    )

    if booking.status not in ["CANCELLED", "COMPLETED"]:
        booking.status = "CANCELLED"
        booking.save(update_fields=["status"])

        messages.success(
            request,
            "Your booking has been cancelled successfully."
        )

    return redirect("booking_list")