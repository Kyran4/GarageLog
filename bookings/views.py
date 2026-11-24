import calendar
import datetime
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import AdminRequiredMixin, RoleRequiredMixin
from accounts.models import User
from inventory.models import StockItem
from vehicles.models import Vehicle
from workshops.models import Workshop

from . import scheduling
from .forms import (
    BookingForm,
    QuoteForm,
    QuoteLabourFormSet,
    QuotePartFormSet,
    StaffBookingForm,
)
from .models import (
    Booking,
    BookingQuoteLabour,
    BookingQuotePart,
    CourtesyReservation,
    CourtesyVehicle,
    EarlierSlotOffer,
    ServiceLabourRecommendation,
)
from .signals import offer_earlier_slot_to_next_customer


class BookingQuerysetMixin(LoginRequiredMixin):
    """Each role only ever sees its own slice of the bookings.

    Customers see their own bookings, mechanics see every booking at the workshop they are
    assigned to, and admins see everything. Anything outside that slice is a 404, so URLs
    cannot be guessed to read it.
    """

    def get_queryset(self):
        user = self.request.user
        bookings = Booking.objects.select_related("customer", "mechanic", "vehicle", "workshop")
        if user.is_admin_role:
            return bookings
        if user.is_mechanic:
            return bookings.filter(workshop_id=user.workshop_id) if user.workshop_id else bookings.none()
        return bookings.filter(customer=user)


class BookingListView(BookingQuerysetMixin, ListView):
    template_name = "bookings/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 20

    SORT_OPTIONS = {
        "date_asc": ("Oldest date", ("booking_date", "booking_time")),
        "date_desc": ("Newest date", ("-booking_date", "-booking_time")),
        "time_asc": ("Time (earliest first)", ("booking_time", "booking_date")),
        "time_desc": ("Time (latest first)", ("-booking_time", "booking_date")),
        "service": ("Service (A-Z)", ("service_type", "-booking_date", "-booking_time")),
        "status": ("Status", ("status", "-booking_date", "-booking_time")),
    }

    def _is_staff(self):
        user = self.request.user
        return user.is_admin_role or user.is_mechanic

    def get_selected_month(self):
        try:
            month = datetime.datetime.strptime(
                self.request.GET.get("month", ""), "%Y-%m"
            ).date().replace(day=1)
            if not 1900 <= month.year <= 9998:
                raise ValueError
            return month
        except ValueError:
            return timezone.localdate().replace(day=1)

    def get_view_mode(self):
        return "calendar" if self.request.GET.get("view") == "calendar" else "list"

    def get_paginate_by(self, queryset):
        return None if self.get_view_mode() == "calendar" else self.paginate_by


    def get_queryset(self):
        bookings = super().get_queryset()

        user = self.request.user

        # Hide cancelled bookings from customers only
        if user.is_customer:
            bookings = bookings.exclude(status="CANCELLED")

        # Staff (mechanics and admins) can filter by status
        if self._is_staff():
            status = self.request.GET.get("status", "")
            if status in dict(Booking.STATUS_CHOICES):
                bookings = bookings.filter(status=status)

        if self.get_view_mode() == "calendar":
            month = self.get_selected_month()
            next_month = (
                month.replace(day=28) + datetime.timedelta(days=4)
            ).replace(day=1)
            bookings = bookings.filter(
                booking_date__gte=month,
                booking_date__lt=next_month,
            ).order_by("booking_date", "booking_time")
        else:
            selected_sort = self.request.GET.get("sort", "date_desc")
            ordering = self.SORT_OPTIONS.get(
                selected_sort, self.SORT_OPTIONS["date_desc"]
            )[1]
            bookings = bookings.order_by(*ordering)

        return bookings


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["is_admin"] = user.is_admin_role
        context["is_mechanic"] = user.is_mechanic
        context["can_create"] = True
        if user.is_admin_role:
            context["page_title"] = "All bookings"
        elif user.is_mechanic:
            context["page_title"] = f"Bookings at {user.workshop}" if user.workshop_id else "Bookings"
        else:
            context["page_title"] = "My bookings"
        context["view_mode"] = self.get_view_mode()
        context["sort_options"] = [
            (key, label) for key, (label, _) in self.SORT_OPTIONS.items()
        ]
        selected_sort = self.request.GET.get("sort", "date_desc")
        context["selected_sort"] = (
            selected_sort if selected_sort in self.SORT_OPTIONS else "date_desc"
        )
        month = self.get_selected_month()
        context["selected_month"] = month
        context["month_label"] = month.strftime("%B %Y")
        context["previous_month"] = (month - datetime.timedelta(days=1)).replace(day=1)
        context["next_month"] = (
            month.replace(day=28) + datetime.timedelta(days=4)
        ).replace(day=1)
        if context["view_mode"] == "calendar":
            bookings_by_date = {}
            for booking in context["bookings"]:
                bookings_by_date.setdefault(booking.booking_date, []).append(booking)
            context["calendar_weeks"] = [
                [
                    {
                        "date": day,
                        "in_month": day.month == month.month,
                        "bookings": bookings_by_date.get(day, []),
                    }
                    for day in week
                ]
                for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
                    month.year, month.month
                )
            ]
        if self._is_staff():
            current = self.request.GET.get("status", "")
            context["status_filter"] = current if current in dict(Booking.STATUS_CHOICES) else ""
            context["status_options"] = [("", "All")] + Booking.STATUS_CHOICES
        return context


class BookingDetailView(BookingQuerysetMixin, DetailView):
    template_name = "bookings/booking_detail.html"
    context_object_name = "booking"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["can_edit"] = self.object.can_be_edited_by(user)
        context["can_cancel"] = self.object.can_be_cancelled_by(user)
        context["can_quote"] = self.object.can_be_quoted_by(user)
        context["can_accept_quote"] = self.object.can_accept_quote_by(user)
        context["can_decline_quote"] = (
            self.object.status == "QUOTED"
            and self.object.customer_id == user.pk
        )
        context["has_estimated_parts"] = self.object.quote_parts.filter(is_estimate=True).exists()
        context["is_admin"] = user.is_admin_role
        context["earlier_slot_offers"] = (
            self.object.earlier_slot_offers.filter(
                status=EarlierSlotOffer.STATUS_PENDING,
                source_booking__status="CANCELLED",
            ).select_related("source_booking")
            if user.pk == self.object.customer_id
            else EarlierSlotOffer.objects.none()
        )
        context["can_check_in"] = (
            user.is_admin_role
            or (user.is_mechanic and user.workshop_id == self.object.workshop_id)
        )
        context["courtesy_vehicles"] = CourtesyVehicle.objects.filter(
            workshop=self.object.workshop,
            is_active=True,
        ).order_by("plate")
        return context


class BookingSaveMixin:
    """Shared by the create and edit views: picks the form for the role and saves safely."""

    template_name = "bookings/create_booking.html"

    def get_form_class(self):
        return BookingForm if self.request.user.is_customer else StaffBookingForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("booking_detail", kwargs={"pk": self.object.pk})

    def save_booking(self, form):
        """Save inside a transaction and re-check the slot, so two people booking the same
        slot at the same moment cannot both get it. Returns True when saved."""
        booking = form.instance
        try:
            with transaction.atomic():
                scheduling.lock_capacity(booking.workshop)
                if (
                    booking.status in Booking.ACTIVE_STATUSES
                    and scheduling.booked_count(booking.workshop, booking.booking_date, booking.booking_time, booking.pk)
                    >= scheduling.capacity(booking.workshop)
                ):
                    form.add_error("booking_time", "That time was just taken. Please choose another time.")
                    return False
                self.object = form.save()
        except IntegrityError:
            form.add_error(None, "That time was just taken by another booking. Please choose a different time.")
            return False
        return True


class BookingCreateView(BookingSaveMixin, RoleRequiredMixin, CreateView):
    allowed_roles = (User.Role.CUSTOMER, User.Role.MECHANIC, User.Role.ADMIN)

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated:
            if user.is_customer:
                if not Workshop.objects.bookable().exists():
                    messages.info(request, "No workshops are taking bookings yet. Please check back soon.")
                    return redirect("dashboard")
                if not Vehicle.objects.filter(owner=user).exists():
                    messages.info(request, "Add your vehicle first, then you can book a service for it.")
                    return redirect("vehicles:create")
            elif user.is_mechanic and not user.workshop_id:
                messages.error(request, "You aren't assigned to a workshop yet, so you can't make bookings. "
                                        "Ask an admin to assign you.")
                return redirect("dashboard")
            elif user.is_mechanic and user.workshop.is_parts_warehouse:
                messages.info(request, f"{user.workshop.name} is the parts warehouse and doesn't take bookings.")
                return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        vehicle_id = self.request.GET.get("vehicle")
        if vehicle_id and vehicle_id.isdigit():
            initial["vehicle"] = vehicle_id
            if not self.request.user.is_customer:
                # Booking from a vehicle's page: start with that vehicle's owner selected.
                owner_id = Vehicle.objects.filter(pk=vehicle_id).values_list("owner_id", flat=True).first()
                if owner_id:
                    initial["customer"] = owner_id
        repeat_id = self.request.GET.get("repeat")
        if repeat_id and repeat_id.isdigit():
            previous = Booking.objects.filter(
                pk=repeat_id,
                status="COMPLETED",
            )
            if self.request.user.is_customer:
                previous = previous.filter(customer=self.request.user)
            previous = previous.select_related("vehicle", "workshop").first()
            if previous:
                initial["vehicle"] = previous.vehicle_id
                initial["workshop"] = previous.workshop_id
                initial["service_type"] = previous.service_type
                initial["notes"] = previous.notes
                initial["same_issue_returned"] = True
                self.repeat_booking = previous
        return initial

    def form_valid(self, form):
        if self.request.user.is_customer:
            form.instance.customer = self.request.user
        previous = getattr(self, "repeat_booking", None)
        if previous and form.cleaned_data.get("same_issue_returned"):
            form.instance.previous_booking = previous
        if not self.save_booking(form):
            return self.form_invalid(form)
        messages.success(self.request, "Your booking has been requested. We'll confirm it shortly."
                         if self.request.user.is_customer else "The booking has been created.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Book a service"
        return context


class BookingUpdateView(BookingSaveMixin, BookingQuerysetMixin, UpdateView):
    context_object_name = "booking"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if (
            not self.request.user.is_customer
            and hasattr(self.object, "job_card")
        ):
            form.fields["open_invoice"] = forms.BooleanField(
                required=False,
                label="Open invoice after completing the service",
                help_text="When selected, save changes and open this job's invoice if service status is Completed.",
                widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
            )
        return form

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        if not booking.can_be_edited_by(self.request.user):
            raise PermissionDenied
        self.original_status = booking.status
        return booking

    def form_valid(self, form):
        open_invoice = form.cleaned_data.get("open_invoice", False)
        completes_service = form.cleaned_data.get("status") == "COMPLETED" and self.original_status != "COMPLETED"
        if not self.save_booking(form):
            return self.form_invalid(form)
        messages.success(self.request, "The booking has been updated.")
        if open_invoice and completes_service and hasattr(self.object, "job_card"):
            return redirect("jobcard_invoice", pk=self.object.job_card.pk)
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit booking"
        return context


class BookingQuoteView(BookingQuerysetMixin, DetailView):
    """Mechanics accept a pending booking and attach a quote."""

    template_name = "bookings/booking_quote.html"
    context_object_name = "booking"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["labour_recommendation"] = ServiceLabourRecommendation.objects.filter(
            service_type=self.object.service_type,
        ).first()
        return context

    def get_object(self, queryset=None):
        booking = super().get_object()
        if not booking.can_be_quoted_by(self.request.user):
            raise PermissionDenied
        return booking

    def get_formsets(self, data=None):
        bound_data = {"data": data} if data is not None else {}
        return (
            QuotePartFormSet(
                prefix="parts",
                workshop=self.object.workshop,
                form_kwargs={"workshop": self.object.workshop, "vehicle": self.object.vehicle},
                **bound_data,
            ),
            QuoteLabourFormSet(prefix="labour", **bound_data),
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = QuoteForm(booking=self.object, user=request.user)
        part_formset, labour_formset = self.get_formsets()
        return self.render_to_response(self.get_context_data(
            form=form,
            part_formset=part_formset,
            labour_formset=labour_formset,
        ))

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = QuoteForm(request.POST, booking=self.object, user=request.user)
        part_formset, labour_formset = self.get_formsets(request.POST)
        form_valid = form.is_valid()
        parts_valid = part_formset.is_valid()
        labour_valid = labour_formset.is_valid()
        if not (form_valid and parts_valid and labour_valid):
            return self.render_to_response(self.get_context_data(
                form=form,
                part_formset=part_formset,
                labour_formset=labour_formset,
            ))

        parts = []
        for line in part_formset.forms:
            item = getattr(line, "cleaned_data", {})
            if item and not item.get("DELETE") and item.get("source") in {"STOCK", "MANUAL"}:
                parts.append(item)
        labour = []
        for line in labour_formset.forms:
            item = getattr(line, "cleaned_data", {})
            if item and not item.get("DELETE") and item.get("description"):
                labour.append(item)
        if not parts and not labour:
            form.add_error(None, "Add at least one part or labour item to the quote.")
            return self.render_to_response(self.get_context_data(
                form=form,
                part_formset=part_formset,
                labour_formset=labour_formset,
            ))

        mechanic = request.user
        if request.user.is_admin_role:
            mechanic = form.cleaned_data.get("mechanic")
            if mechanic is None:
                form.add_error("mechanic", "Choose a mechanic to assign this quote.")
                return self.render_to_response(self.get_context_data(
                    form=form,
                    part_formset=part_formset,
                    labour_formset=labour_formset,
                ))

        if self.object._clashes(mechanic_id=mechanic.pk):
            form.add_error("mechanic", "That mechanic is already booked at this time.")
            return self.render_to_response(self.get_context_data(
                form=form,
                part_formset=part_formset,
                labour_formset=labour_formset,
            ))

        with transaction.atomic():
            stock_parts = [line for line in parts if line["source"] == "STOCK"]
            stock_ids = {line["stock_item"].pk for line in stock_parts}
            locked_stock = {
                item.pk: item
                for item in (
                    StockItem.objects.select_for_update()
                    .filter(pk__in=stock_ids, workshop=self.object.workshop)
                    .select_related("part")
                )
            }
            requested_stock = {}
            for line in stock_parts:
                stock_item_id = line["stock_item"].pk
                requested_stock[stock_item_id] = (
                    requested_stock.get(stock_item_id, 0) + line["quantity"]
                )
            unavailable = next(
                (
                    item_id for item_id, quantity in requested_stock.items()
                    if quantity > getattr(locked_stock.get(item_id), "quantity", 0)
                ),
                None,
            )
            if unavailable is not None:
                for line in part_formset.forms:
                    if (
                        getattr(line, "cleaned_data", {}).get("stock_item")
                        and line.cleaned_data["stock_item"].pk == unavailable
                    ):
                        line.add_error(
                            "quantity",
                            "The requested quantity exceeds the workshop's current stock.",
                        )
                        break
                else:
                    form.add_error(None, "The selected part no longer has enough stock.")
                return self.render_to_response(self.get_context_data(
                    form=form,
                    part_formset=part_formset,
                    labour_formset=labour_formset,
                ))

            for line in parts:
                if line["source"] == "STOCK":
                    line["stock_item"] = locked_stock[line["stock_item"].pk]
            quote_total = sum(
                (
                    line["stock_item"].price * line["quantity"]
                    if line["source"] == "STOCK"
                    else line["estimated_unit_price"] * line["quantity"]
                    for line in parts
                ),
                Decimal("0.00"),
            ) + sum(
                (line["charge"] for line in labour),
                Decimal("0.00"),
            )
            if quote_total > Decimal("99999999.99"):
                form.add_error(None, "The quote total is above the maximum supported amount.")
                return self.render_to_response(self.get_context_data(
                    form=form,
                    part_formset=part_formset,
                    labour_formset=labour_formset,
                ))
            for line in parts:
                BookingQuotePart.objects.create(
                    booking=self.object,
                    stock_item=line["stock_item"] if line["source"] == "STOCK" else None,
                    manual_description=(
                        "" if line["source"] == "STOCK" else line["manual_description"]
                    ),
                    is_estimate=line["source"] == "MANUAL",
                    quantity=line["quantity"],
                    unit_price=(
                        line["stock_item"].price
                        if line["source"] == "STOCK"
                        else line["estimated_unit_price"]
                    ),
                )
            for line in labour:
                BookingQuoteLabour.objects.create(
                    booking=self.object,
                    description=line["description"].strip(),
                    charge=line["charge"],
                )
            self.object.mechanic = mechanic
            self.object.quote_amount = quote_total
            self.object.quote_notes = form.cleaned_data["quote_notes"].strip()
            self.object.quoted_at = timezone.now()
            self.object.status = "QUOTED"
            self.object.save(update_fields=[
                "mechanic", "quote_amount", "quote_notes", "quoted_at", "status",
            ])
        messages.success(request, "The quote has been sent to the customer.")
        return redirect("booking_detail", pk=self.object.pk)


class BookingAcceptQuoteView(BookingQuerysetMixin, DetailView):
    """Customer accepts the mechanic's quote and finalizes the booking."""

    def get_object(self, queryset=None):
        booking = super().get_object()
        if not booking.can_accept_quote_by(self.request.user):
            raise PermissionDenied
        return booking

    def post(self, request, *args, **kwargs):
        booking = self.get_object()
        try:
            with transaction.atomic():
                scheduling.lock_capacity(booking.workshop)
                if booking._clashes(vehicle_id=booking.vehicle_id) or (
                    booking.mechanic_id and booking._clashes(mechanic_id=booking.mechanic_id)
                ):
                    raise IntegrityError
                booking.status = "CONFIRMED"
                booking.quote_accepted_at = timezone.now()
                booking.save(update_fields=["status", "quote_accepted_at"])
        except IntegrityError:
            messages.error(request, "The vehicle or mechanic is no longer available at that time.")
            return redirect("booking_detail", pk=booking.pk)

        messages.success(request, "Quote accepted. Your booking is confirmed.")
        return redirect("booking_detail", pk=booking.pk)


class BookingDeclineQuoteView(BookingQuerysetMixin, DetailView):
    """Customer declines a quote and cancels the booking."""

    def get_object(self, queryset=None):
        booking = super().get_object()
        if not (
            booking.status == "QUOTED"
            and booking.customer_id == self.request.user.pk
        ):
            raise PermissionDenied
        return booking

    def post(self, request, *args, **kwargs):
        booking = self.get_object()
        booking.status = "CANCELLED"
        booking.save(update_fields=["status"])
        messages.success(request, "The quote was declined and the booking has been cancelled.")
        return redirect("booking_detail", pk=booking.pk)


class BookingCancelView(BookingQuerysetMixin, DetailView):
    """Asks for confirmation (GET) and then cancels the booking (POST). The booking is kept."""

    template_name = "bookings/booking_confirm_cancel.html"
    context_object_name = "booking"

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        if not booking.can_be_cancelled_by(self.request.user):
            raise PermissionDenied
        return booking

    def post(self, request, *args, **kwargs):
        booking = self.get_object()
        booking.status = "CANCELLED"
        booking.save(update_fields=["status"])
        messages.success(request, "The booking has been cancelled.")
        return redirect("booking_list")


class EarlierSlotOfferAcceptView(LoginRequiredMixin, View):
    def post(self, request, offer_pk):
        with transaction.atomic():
            offer = get_object_or_404(
                EarlierSlotOffer.objects.select_for_update().select_related(
                    "source_booking__workshop",
                    "target_booking",
                ),
                pk=offer_pk,
                target_booking__customer=request.user,
            )
            target = offer.target_booking
            source = offer.source_booking

            if offer.status != EarlierSlotOffer.STATUS_PENDING:
                messages.info(request, "This earlier-time offer is no longer available.")
                return redirect("booking_detail", pk=target.pk)

            eligible = (
                source.status == "CANCELLED"
                and source.starts_at >= timezone.now()
                and target.is_upcoming
                and target.earlier_slot_opt_in
                and target.workshop_id == source.workshop_id
                and target.booking_date == source.booking_date
                and target.booking_time > source.booking_time
            )
            scheduling.lock_capacity(source.workshop)
            same_slot = Booking.objects.filter(
                workshop_id=source.workshop_id,
                booking_date=source.booking_date,
                booking_time=source.booking_time,
                status__in=Booking.ACTIVE_STATUSES,
            ).exclude(pk=target.pk)
            at_capacity = same_slot.count() >= scheduling.capacity(source.workshop)
            conflicts = (
                (target.vehicle_id and same_slot.filter(vehicle_id=target.vehicle_id).exists())
                or (target.mechanic_id and same_slot.filter(mechanic_id=target.mechanic_id).exists())
            )

            if not eligible or at_capacity or conflicts:
                offer.status = (
                    EarlierSlotOffer.STATUS_UNAVAILABLE
                    if eligible
                    else EarlierSlotOffer.STATUS_WITHDRAWN
                )
                offer.responded_at = timezone.now()
                offer.save(update_fields=["status", "responded_at"])
                offer_earlier_slot_to_next_customer(source)
                messages.warning(
                    request,
                    "That earlier time is no longer available. Your existing booking has not changed.",
                )
                return redirect("booking_detail", pk=target.pk)

            offer.status = EarlierSlotOffer.STATUS_ACCEPTED
            offer.responded_at = timezone.now()
            offer.save(update_fields=["status", "responded_at"])
            target.booking_date = source.booking_date
            target.booking_time = source.booking_time
            try:
                with transaction.atomic():
                    target.save(update_fields=["booking_date", "booking_time"])
            except IntegrityError:
                offer.status = EarlierSlotOffer.STATUS_UNAVAILABLE
                offer.responded_at = timezone.now()
                offer.save(update_fields=["status", "responded_at"])
                offer_earlier_slot_to_next_customer(source)
                messages.warning(
                    request,
                    "That earlier time was just taken. Your existing booking has not changed.",
                )
                return redirect("booking_detail", pk=target.pk)

        messages.success(
            request,
            f"Your booking has been moved to {source.booking_date:%A} "
            f"{source.booking_date.day} {source.booking_date:%B} "
            f"at {scheduling.format_time(source.booking_time)}.",
        )
        return redirect("booking_detail", pk=target.pk)


class EarlierSlotOfferDeclineView(LoginRequiredMixin, View):
    def post(self, request, offer_pk):
        with transaction.atomic():
            offer = get_object_or_404(
                EarlierSlotOffer.objects.select_for_update().select_related(
                    "source_booking",
                    "target_booking",
                ),
                pk=offer_pk,
                target_booking__customer=request.user,
            )
            if offer.status == EarlierSlotOffer.STATUS_PENDING:
                offer.status = EarlierSlotOffer.STATUS_DECLINED
                offer.responded_at = timezone.now()
                offer.save(update_fields=["status", "responded_at"])
                offer_earlier_slot_to_next_customer(offer.source_booking)
                messages.info(request, "You declined the earlier-time offer. Your booking is unchanged.")
            target_booking_id = offer.target_booking_id
        return redirect("booking_detail", pk=target_booking_id)


class BookingRepeatView(BookingQuerysetMixin, View):
    """Open a repeat booking from a completed repair."""

    def post(self, request, pk):
        previous = get_object_or_404(self.get_queryset(), pk=pk, status="COMPLETED")
        params = f"?repeat={previous.pk}"
        if previous.vehicle_id:
            params += f"&vehicle={previous.vehicle_id}"
        return redirect(f"{reverse('create_booking')}{params}")


class BookingDropoffCheckinView(BookingQuerysetMixin, View):
    def post(self, request, pk):
        booking = get_object_or_404(self.get_queryset(), pk=pk)
        if not (
            request.user.is_admin_role
            or (request.user.is_mechanic and request.user.workshop_id == booking.workshop_id)
        ):
            raise PermissionDenied
        if booking.dropoff_checked_in_at:
            messages.error(request, "This vehicle has already been checked in.")
            return redirect("booking_detail", pk=booking.pk)
        booking.dropoff_contact = request.POST.get("dropoff_contact", "").strip()
        booking.dropoff_details = request.POST.get("dropoff_details", "").strip()
        booking.dropoff_issue = request.POST.get("dropoff_issue", "").strip()
        booking.dropoff_checked_in_at = timezone.now()
        booking.dropoff_checked_in_by = request.user
        booking.save(update_fields=[
            "dropoff_contact",
            "dropoff_details",
            "dropoff_issue",
            "dropoff_checked_in_at",
            "dropoff_checked_in_by",
        ])
        messages.success(request, "Vehicle drop-off check-in recorded.")
        return redirect("booking_detail", pk=booking.pk)


class BookingCourtesyAssignView(BookingQuerysetMixin, View):
    def post(self, request, pk):
        booking = get_object_or_404(self.get_queryset(), pk=pk)
        if not (
            request.user.is_admin_role
            or (request.user.is_mechanic and request.user.workshop_id == booking.workshop_id)
        ):
            raise PermissionDenied
        vehicle = get_object_or_404(
            CourtesyVehicle,
            pk=request.POST.get("courtesy_vehicle"),
            workshop=booking.workshop,
            is_active=True,
        )
        try:
            start_date = datetime.datetime.strptime(
                request.POST.get("start_date") or "", "%Y-%m-%d"
            ).date()
            end_date = datetime.datetime.strptime(
                request.POST.get("end_date") or "", "%Y-%m-%d"
            ).date()
        except ValueError:
            messages.error(request, "Enter valid courtesy vehicle collection and return dates.")
            return redirect("booking_detail", pk=booking.pk)

        reservation = CourtesyReservation(
            booking=booking,
            vehicle=vehicle,
            start_date=start_date,
            end_date=end_date,
            assigned_by=request.user,
        )
        try:
            reservation.full_clean()
        except ValidationError as exc:
            message = next(iter(exc.message_dict.values()))[0]
            messages.error(request, message)
            return redirect("booking_detail", pk=booking.pk)
        reservation.save()
        booking.courtesy_vehicle_requested = True
        booking.courtesy_vehicle_start = start_date
        booking.courtesy_vehicle_end = end_date
        booking.save(update_fields=[
            "courtesy_vehicle_requested",
            "courtesy_vehicle_start",
            "courtesy_vehicle_end",
        ])
        messages.success(request, f"Courtesy vehicle {vehicle.plate} has been assigned.")
        return redirect("booking_detail", pk=booking.pk)


class BookingDeleteView(AdminRequiredMixin, DeleteView):
    """Permanently removes a booking. Admins only; customers cancel instead."""

    model = Booking
    template_name = "bookings/booking_confirm_delete.html"
    context_object_name = "booking"
    success_url = reverse_lazy("booking_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "The booking has been deleted.")
        return response
