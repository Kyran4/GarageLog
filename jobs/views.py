import csv
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from bookings.models import Booking
from inventory.models import Part, StockItem, parts_matching
from workshops.models import Workshop

from .forms import JobCardForm, JobPartForm, SupplierOrderForm
from .models import JobCard, JobPart, SupplierOrder


def csv_safe_text(value):
    text = str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


class JobCardQuerysetMixin:
    """Mechanics only ever get their own job cards. Admins get all of them.

    Anything outside that slice is a 404, so URLs cannot be guessed to read it.
    """

    def get_queryset(self):
        job_cards = JobCard.objects.select_related(
            "booking",
            "booking__vehicle",
            "booking__customer",
            "booking__workshop",
            "mechanic",
        ).order_by("-created_at")

        user = self.request.user
        if user.is_admin_role:
            return job_cards
        return job_cards.filter(mechanic=user)


class JobCardListView(JobCardQuerysetMixin, RoleRequiredMixin, ListView):
    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)
    template_name = "jobs/jobcard_list.html"
    context_object_name = "job_cards"
    paginate_by = 20

    def get_queryset(self):
        job_cards = super().get_queryset()
        if self.request.GET.get("overdue") == "1":
            job_cards = job_cards.filter(
                booking__booking_date__lt=timezone.localdate(),
                booking__status__in=("CONFIRMED", "IN_PROGRESS"),
            )
        return job_cards

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("overdue") == "1":
            context["page_title"] = "Overdue job cards"
        else:
            context["page_title"] = "All job cards" if self.request.user.is_admin_role else "My job cards"
        return context


class JobCardDetailView(JobCardQuerysetMixin, RoleRequiredMixin, UpdateView):
    """Shows one job card with the booking details, and lets the mechanic update it."""

    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)
    model = JobCard
    form_class = JobCardForm
    template_name = "jobs/jobcard_form.html"
    context_object_name = "job_card"

    def get_success_url(self):
        return reverse("booking_detail", kwargs={"pk": self.object.booking_id})

    def form_valid(self, form):
        open_invoice = form.cleaned_data["open_invoice"]
        completes_service = (
            form.cleaned_data["status"] == "COMPLETED"
            and self.object.booking.status != "COMPLETED"
        )
        response = super().form_valid(form)
        messages.success(self.request, "The job card has been updated.")
        if open_invoice and completes_service:
            return redirect("jobcard_invoice", pk=self.object.pk)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Job card #{self.object.pk}"
        context["part_form"] = JobPartForm(workshop=self.object.booking.workshop)
        context["checklist_fields"] = [
            context["form"][f"checklist_{key}"]
            for key, _ in JobCardForm.CHECKLIST_ITEMS
        ]
        return context


class JobPartCreateView(JobCardQuerysetMixin, RoleRequiredMixin, CreateView):
    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)
    model = JobPart
    form_class = JobPartForm

    def get_job_card_queryset(self):
        cards = JobCard.objects.select_related("booking__workshop")
        if self.request.user.is_admin_role:
            return cards
        return cards.filter(mechanic=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        self.job_card = get_object_or_404(self.get_job_card_queryset(), pk=self.kwargs["pk"])
        kwargs["workshop"] = self.job_card.booking.workshop
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("source") in JobPart.Source.values:
            initial["source"] = self.request.GET["source"]
            if initial["source"] == JobPart.Source.WAREHOUSE:
                initial["freight_charge"] = "12.99"
        return initial

    def form_valid(self, form):
        with transaction.atomic():
            form.instance.job_card = self.job_card
            part = form.cleaned_data.get("part")
            source = form.cleaned_data["source"]
            if part:
                quantity = form.cleaned_data["quantity"]
                workshop = self.job_card.booking.workshop
                warehouse = Workshop.get_warehouse()
                stock_locations = [
                    (JobPart.Source.WORKSHOP, workshop),
                    (JobPart.Source.WAREHOUSE, warehouse),
                ]
                selected_stock = None
                selected_source = JobPart.Source.WAREHOUSE
                for candidate_source, location in stock_locations:
                    if location is None:
                        continue
                    stock_item = (
                        StockItem.objects.select_for_update()
                        .filter(workshop=location, part=part)
                        .first()
                    )
                    if not stock_item or stock_item.quantity < quantity:
                        continue
                    reserved = StockItem.objects.filter(
                        pk=stock_item.pk,
                        quantity__gte=quantity,
                    ).update(quantity=F("quantity") - quantity)
                    if reserved:
                        selected_stock = stock_item
                        selected_source = candidate_source
                        break

                form.instance.source = selected_source
                form.instance.stock_item = selected_stock
                form.instance.supply_status = (
                    JobPart.SupplyStatus.READY
                    if selected_stock else JobPart.SupplyStatus.BACKORDERED
                )
                if not form.data.get("unit_price"):
                    warehouse_stock = (
                        StockItem.objects.filter(workshop=warehouse, part=part).first()
                        if warehouse else None
                    )
                    price_stock = (
                        selected_stock
                        if selected_stock
                        else warehouse_stock if selected_source == JobPart.Source.WAREHOUSE else None
                    )
                    form.instance.unit_price = price_stock.price if price_stock else part.default_price
                if not form.data.get("freight_charge"):
                    form.instance.freight_charge = (
                        Decimal("12.99")
                        if selected_source == JobPart.Source.WAREHOUSE
                        else Decimal("0.00")
                    )

            response = super().form_valid(form)
            if form.instance.supply_status == JobPart.SupplyStatus.BACKORDERED:
                messages.success(
                    self.request,
                    "The part is out of warehouse stock and has been added to the backorder queue.",
                )
            else:
                messages.success(self.request, "The part has been added to the job card.")
            return response

    def form_invalid(self, form):
        messages.error(self.request, " ".join(
            error for errors in form.errors.values() for error in errors
        ))
        return redirect("jobcard_detail", pk=self.job_card.pk)

    def get_success_url(self):
        return reverse("jobcard_detail", kwargs={"pk": self.job_card.pk})


class JobPartDeleteView(JobCardQuerysetMixin, RoleRequiredMixin, View):
    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)

    def post(self, request, pk, part_id):
        job_card = get_object_or_404(self.get_queryset(), pk=pk)
        part = get_object_or_404(JobPart, pk=part_id, job_card=job_card)
        if hasattr(part, "supplier_order"):
            messages.error(request, "This part has a supplier order. Receive it before removing the job-card part.")
            return redirect("jobcard_detail", pk=job_card.pk)
        part.delete()
        messages.success(request, "The part has been removed from the job card.")
        return redirect("jobcard_detail", pk=job_card.pk)


class WarehouseStaffRequiredMixin(RoleRequiredMixin):
    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)

    def test_func(self):
        user = self.request.user
        return user.is_admin_role or (
            user.is_mechanic and user.workshop_id and user.workshop.is_parts_warehouse
        )


class SupplierOrderListView(WarehouseStaffRequiredMixin, ListView):
    template_name = "jobs/supplier_order_list.html"
    context_object_name = "supplier_orders"
    paginate_by = 30

    def get_queryset(self):
        return SupplierOrder.objects.select_related(
            "job_part__job_card__booking__workshop",
            "job_part__job_card__mechanic",
            "job_part__part",
            "part",
            "ordered_by",
            "received_by",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["backorders"] = JobPart.objects.filter(
            source=JobPart.Source.WAREHOUSE,
            supply_status=JobPart.SupplyStatus.BACKORDERED,
        ).select_related(
            "job_card__booking__workshop",
            "job_card__mechanic",
            "part",
        )
        return context


class SupplierOrderCreateView(WarehouseStaffRequiredMixin, CreateView):
    model = SupplierOrder
    form_class = SupplierOrderForm
    template_name = "jobs/supplier_order_form.html"

    def get_job_part(self):
        if not hasattr(self, "job_part"):
            part_id = self.kwargs.get("part_id")
            self.job_part = (
                get_object_or_404(
                    JobPart.objects.select_related("job_card__booking__workshop", "part"),
                    pk=part_id,
                    source=JobPart.Source.WAREHOUSE,
                    supply_status=JobPart.SupplyStatus.BACKORDERED,
                )
                if part_id is not None else None
            )
        return self.job_part

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["job_part"] = self.get_job_part()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        job_part = self.get_job_part()
        if job_part:
            part = job_part.part
            initial["part"] = part.pk
            initial["quantity"] = job_part.quantity
            initial["unit_cost"] = (
                job_part.unit_cost
                if job_part.unit_cost is not None
                else self._default_unit_cost(part)
            )
        else:
            part_id = self.request.GET.get("part", "")
            if part_id.isdigit():
                part = Part.objects.filter(pk=part_id, is_active=True).first()
                if part:
                    initial["part"] = part.pk
                    initial["quantity"] = self.request.GET.get("quantity", "1")
                    initial["unit_cost"] = self._default_unit_cost(part)
        return initial

    @staticmethod
    def _default_unit_cost(part):
        warehouse = Workshop.get_warehouse()
        stock = (
            StockItem.objects.filter(workshop=warehouse, part=part).first()
            if warehouse else None
        )
        return stock.unit_cost if stock and stock.unit_cost is not None else part.default_price

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["job_part"] = self.get_job_part()
        return context

    def form_valid(self, form):
        job_part_request = self.get_job_part()
        with transaction.atomic():
            if job_part_request:
                job_part = JobPart.objects.select_for_update().get(pk=job_part_request.pk)
                if job_part.supply_status != JobPart.SupplyStatus.BACKORDERED:
                    form.add_error(None, "This backorder has already been processed.")
                    return self.form_invalid(form)
                form.instance.job_part = job_part
                job_part.supply_status = JobPart.SupplyStatus.ON_ORDER
                job_part.save(update_fields=["supply_status"])
            form.instance.part = form.cleaned_data["part"]
            form.instance.quantity = form.cleaned_data["quantity"]
            form.instance.ordered_by = self.request.user
            response = super().form_valid(form)
        order_type = (
            f"backorder for {job_part_request.name}"
            if job_part_request
            else f"{form.instance.quantity} × {form.instance.part.name} for warehouse stock"
        )
        messages.success(self.request, f"Supplier order recorded: {order_type}.")
        return response

    def get_success_url(self):
        return reverse("supplier_order_list")


class SupplierOrderReceiveView(WarehouseStaffRequiredMixin, View):
    def post(self, request, pk):
        with transaction.atomic():
            order = get_object_or_404(
                SupplierOrder.objects.select_for_update().select_related("job_part", "part"),
                pk=pk,
            )
            job_part = (
                JobPart.objects.select_for_update().get(pk=order.job_part_id)
                if order.job_part_id else None
            )
            if order.received_at or (
                job_part and (
                    job_part.supply_status != JobPart.SupplyStatus.ON_ORDER
                    or job_part.stock_item_id
                )
            ):
                messages.error(request, "This supplier order is not awaiting receipt.")
                return redirect("supplier_order_list")

            warehouse = Workshop.get_warehouse()
            if warehouse is None:
                messages.error(request, "Set up a parts warehouse before receiving supplier orders.")
                return redirect("supplier_order_list")

            stock_item, _ = StockItem.objects.get_or_create(
                workshop=warehouse,
                part=order.part,
                defaults={"quantity": 0, "unit_price": order.part.default_price},
            )
            stock_item = StockItem.objects.select_for_update().get(pk=stock_item.pk)
            StockItem.objects.filter(pk=stock_item.pk).update(
                quantity=F("quantity") + order.quantity
            )
            stock_item.unit_cost = order.unit_cost
            stock_item.save(update_fields=["unit_cost", "updated_at"])
            if job_part:
                StockItem.objects.filter(
                    pk=stock_item.pk,
                    quantity__gte=job_part.quantity,
                ).update(quantity=F("quantity") - job_part.quantity)
                job_part.stock_item = stock_item
                job_part.unit_cost = order.unit_cost
                job_part.supply_status = JobPart.SupplyStatus.READY
                job_part.save(update_fields=["stock_item", "unit_cost", "supply_status"])
            order.received_by = request.user
            order.received_at = timezone.now()
            order.save(update_fields=["received_by", "received_at"])

        if job_part:
            message = f"Received {job_part.quantity} × {job_part.name} into the job allocation."
        else:
            message = f"Received {order.quantity} × {order.part.name} into warehouse stock."
        messages.success(request, message)
        return redirect("supplier_order_list")


class InvoiceAccessMixin(LoginRequiredMixin):
    """Invoices are visible to the owning customer, assigned mechanic, and admins only."""

    def get_queryset(self):
        cards = JobCard.objects.select_related(
            "booking__customer", "booking__vehicle", "booking__workshop", "mechanic"
        ).prefetch_related("parts")
        user = self.request.user
        if user.is_admin_role:
            return cards
        if user.is_mechanic:
            return cards.filter(mechanic=user)
        return cards.filter(booking__customer=user, booking__status="COMPLETED")


class InvoiceView(InvoiceAccessMixin, DetailView):
    model = JobCard
    template_name = "jobs/invoice.html"
    context_object_name = "job_card"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        checklist = self.object.checklist or {}
        choice_labels = dict(JobCardForm.CHECKLIST_CHOICES)
        context["checklist_rows"] = [
            {
                "label": label,
                "status": choice_labels.get(checklist.get(key), "Not checked"),
            }
            for key, label in JobCardForm.CHECKLIST_ITEMS
        ]
        return context


class InvoiceExportView(InvoiceAccessMixin, View):
    def get(self, request, pk):
        job_card = get_object_or_404(self.get_queryset(), pk=pk)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="invoice-{job_card.pk}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Invoice", f"Job card #{job_card.pk}"])
        writer.writerow(["Customer", csv_safe_text(job_card.booking.customer.get_full_name() or job_card.booking.customer.username)])
        writer.writerow(["Service", csv_safe_text(job_card.booking.service_type)])
        writer.writerow(["Vehicle", csv_safe_text(job_card.booking.vehicle or "")])
        writer.writerow(["Work completed", csv_safe_text(job_card.work_done)])
        writer.writerow([])
        writer.writerow(["Item", "Quantity", "Unit price", "Total"])
        writer.writerow(["Labour", 1, job_card.labor_charge, job_card.labor_charge])
        for item in job_card.parts.all():
            writer.writerow([csv_safe_text(item.name), item.quantity, item.unit_price, item.line_total])
            if item.freight_charge:
                writer.writerow([csv_safe_text(item.freight_description), 1, item.freight_charge, item.freight_charge])
        writer.writerow(["Total", "", "", job_card.invoice_total])
        return response


class PartSearchView(RoleRequiredMixin, View):
    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)

    def get(self, request, pk):
        cards = JobCard.objects.select_related("booking__workshop")
        if not request.user.is_admin_role:
            cards = cards.filter(mechanic=request.user)
        job_card = get_object_or_404(cards, pk=pk)
        query = request.GET.get("q", "").strip()
        show_all = request.GET.get("all") == "1"
        try:
            page = max(1, int(request.GET.get("page", "1")))
        except ValueError:
            page = 1

        vehicle = job_card.booking.vehicle
        parts = Part.objects.filter(is_active=True)
        if not show_all and vehicle:
            parts = parts_matching(vehicle.make, vehicle.model, vehicle.year, parts)
        if query:
            if len(query) < 2:
                return JsonResponse({"results": [], "has_more": False, "total": 0})
            parts = parts.filter(
                Q(name__icontains=query)
                | Q(part_number__icontains=query)
                | Q(brand__icontains=query)
            )
        parts = parts.order_by("universal", "category", "name", "pk")
        page_size = 50
        offset = (page - 1) * page_size
        total = parts.count()
        parts = list(parts[offset:offset + page_size + 1])
        has_more = len(parts) > page_size
        parts = parts[:page_size]

        warehouse = Workshop.get_warehouse()
        workshop_ids = [job_card.booking.workshop_id]
        if warehouse:
            workshop_ids.append(warehouse.pk)
        stock = {
            (item.workshop_id, item.part_id): item.quantity
            for item in StockItem.objects.filter(workshop_id__in=workshop_ids, part__in=parts)
        }
        return JsonResponse({
            "has_more": has_more,
            "total": total,
            "page": page,
            "vehicle": str(vehicle) if vehicle else "",
            "filtered_by_vehicle": bool(vehicle and not show_all),
            "results": [
                {
                    "id": part.pk,
                    "label": f"{part.part_number} — {part.name}",
                    "universal": part.universal,
                    "workshop_stock": stock.get((job_card.booking.workshop_id, part.pk), 0),
                    "warehouse_stock": stock.get((warehouse.pk, part.pk), 0) if warehouse else 0,
                    "workshop_name": job_card.booking.workshop.name,
                    "warehouse_name": warehouse.name if warehouse else "Parts warehouse",
                }
                for part in parts
            ]
        })


class JobCardCreateView(RoleRequiredMixin, View):
    """Creates the job card for a booking. Only reachable by POST (the button on the booking page)."""

    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)

    def post(self, request, booking_id):
        user = request.user

        # Same rule as the booking pages: a mechanic only reaches bookings at their own workshop.
        bookings = Booking.objects.select_related("workshop", "mechanic")
        if user.is_mechanic:
            bookings = bookings.filter(workshop_id=user.workshop_id)
        booking = get_object_or_404(bookings, pk=booking_id)

        back_to_booking = redirect("booking_detail", pk=booking.pk)

        if booking.status not in ("CONFIRMED", "IN_PROGRESS"):
            messages.error(request, "Only confirmed or in-progress bookings can have a job card.")
            return back_to_booking

        if booking.workshop.is_parts_warehouse:
            messages.error(request, "The parts warehouse does not take bookings, so it has no job cards.")
            return back_to_booking

        # Use the booking's mechanic. A mechanic with no one assigned takes the job themselves.
        mechanic = booking.mechanic
        if mechanic is None and user.is_mechanic:
            mechanic = user
        if mechanic is None:
            messages.error(request, "Assign a mechanic to this booking first, then create the job card.")
            return back_to_booking

        job_card, created = JobCard.objects.get_or_create(
            booking=booking,
            defaults={"mechanic": mechanic},
        )
        if not created:
            messages.info(request, "This booking already has a job card.")
            return back_to_booking

        messages.success(request, "The job card has been created.")
        if user.is_admin_role or job_card.mechanic_id == user.pk:
            return redirect("jobcard_detail", pk=job_card.pk)
        return back_to_booking