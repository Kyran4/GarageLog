from decimal import Decimal

import pytest
from django.urls import reverse

from jobs.models import JobCard, JobPart, SupplierOrder


@pytest.fixture
def job_card(customer, mechanic, make_booking):
    booking = make_booking(
        customer,
        status="CONFIRMED",
        mechanic=mechanic,
        workshop=mechanic.workshop,
    )
    return JobCard.objects.create(
        booking=booking,
        mechanic=mechanic,
        work_done="Replaced the worn component.",
        labor_charge=Decimal("45.00"),
    )


def test_job_card_permissions_are_scoped_to_assigned_mechanic(client, job_card, mechanic, make_user, admin_user):
    detail = reverse("jobcard_detail", kwargs={"pk": job_card.pk})
    client.force_login(job_card.booking.customer)
    assert client.get(detail).status_code == 403

    client.force_login(make_user("other-mechanic", role="MECHANIC", workshop=mechanic.workshop))
    assert client.get(detail).status_code == 404

    client.force_login(mechanic)
    assert client.get(detail).status_code == 200

    client.force_login(admin_user)
    assert client.get(detail).status_code == 200


def test_customer_can_only_view_their_own_invoice(client, job_card, customer, make_user):
    invoice = reverse("jobcard_invoice", kwargs={"pk": job_card.pk})
    export = reverse("jobcard_invoice_export", kwargs={"pk": job_card.pk})
    client.force_login(customer)
    assert client.get(invoice).status_code == 404
    assert client.get(export).status_code == 404

    job_card.booking.status = "COMPLETED"
    job_card.booking.save(update_fields=["status"])
    assert client.get(invoice).status_code == 200
    assert client.get(export).status_code == 200

    other_customer = make_user("other-customer")
    client.force_login(other_customer)
    assert client.get(invoice).status_code == 404


def test_job_card_updates_booking_status_and_can_open_invoice_on_completion(client, job_card):
    client.force_login(job_card.mechanic)
    detail_url = reverse("jobcard_detail", kwargs={"pk": job_card.pk})
    response = client.get(detail_url)
    assert response.status_code == 200
    assert b"Service status" in response.content
    assert b"Open invoice after completing the service" in response.content
    assert b"Job status" not in response.content

    response = client.post(
        detail_url,
        {
            "status": "COMPLETED",
            "description": "Brake repair",
            "work_done": "Replaced the brake pads.",
            "labor_charge": "45.00",
            "open_invoice": "on",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("jobcard_invoice", kwargs={"pk": job_card.pk})
    job_card.booking.refresh_from_db()
    assert job_card.booking.status == "COMPLETED"
    assert not hasattr(job_card, "status")


def test_job_card_status_can_be_changed_without_automatically_opening_invoice(client, job_card):
    client.force_login(job_card.mechanic)
    response = client.post(
        reverse("jobcard_detail", kwargs={"pk": job_card.pk}),
        {
            "status": "IN_PROGRESS",
            "description": "",
            "work_done": "",
            "labor_charge": "0.00",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("booking_detail", kwargs={"pk": job_card.booking_id})
    job_card.booking.refresh_from_db()
    assert job_card.booking.status == "IN_PROGRESS"


def test_job_card_checklist_is_optional_and_persists_responses(client, job_card):
    client.force_login(job_card.mechanic)
    detail_url = reverse("jobcard_detail", kwargs={"pk": job_card.pk})
    page = client.get(detail_url)
    assert page.status_code == 200
    assert b"Optional pre-handover checklist" in page.content
    assert b"not a formal inspection" in page.content

    response = client.post(
        detail_url,
        {
            "status": "IN_PROGRESS",
            "description": job_card.description,
            "work_done": job_card.work_done,
            "labor_charge": "45.00",
            "checklist_tyres": "DONE",
            "checklist_lights": "NOT_APPLICABLE",
            "checklist_leaks": "",
            "checklist_warning_lights": "",
            "checklist_fluids": "",
            "checklist_requested_work": "",
            "checklist_parts_recorded": "",
            "checklist_equipment_removed": "",
            "checklist_handover_check": "",
            "checklist_notes": "Recheck tyre pressure at follow-up.",
        },
    )
    assert response.status_code == 302
    job_card.refresh_from_db()
    assert job_card.checklist == {
        "tyres": "DONE",
        "lights": "NOT_APPLICABLE",
    }
    assert job_card.checklist_notes == "Recheck tyre pressure at follow-up."
    page = client.get(detail_url)
    assert page.context["form"]["checklist_tyres"].value() == "DONE"
    assert page.context["form"]["checklist_lights"].value() == "NOT_APPLICABLE"

    response = client.post(
        detail_url,
        {
            "status": "IN_PROGRESS",
            "description": "",
            "work_done": "",
            "labor_charge": "0.00",
        },
    )
    assert response.status_code == 302
    job_card.refresh_from_db()
    assert job_card.checklist == {}
    assert job_card.checklist_notes == ""


def test_booking_screen_links_invoice_and_can_open_it_when_marking_service_complete(
    client, job_card, booking_data, vehicle
):
    client.force_login(job_card.booking.customer)
    detail_url = reverse("booking_detail", kwargs={"pk": job_card.booking_id})
    detail = client.get(detail_url)
    invoice_url = reverse("jobcard_invoice", kwargs={"pk": job_card.pk})
    assert invoice_url.encode() not in detail.content

    client.force_login(job_card.mechanic)
    detail = client.get(detail_url)
    assert invoice_url.encode() in detail.content

    edit_url = reverse("booking_edit", kwargs={"pk": job_card.booking_id})
    edit_page = client.get(edit_url)
    assert b"Open invoice after completing the service" in edit_page.content
    response = client.post(
        edit_url,
        booking_data(
            vehicle,
            customer=job_card.booking.customer_id,
            mechanic=job_card.mechanic_id,
            status="COMPLETED",
        ) | {"open_invoice": "on"},
    )
    assert response.status_code == 302
    assert response.url == invoice_url
    job_card.booking.refresh_from_db()
    assert job_card.booking.status == "COMPLETED"
    client.force_login(job_card.booking.customer)
    detail = client.get(detail_url)
    assert invoice_url.encode() in detail.content


def test_manual_part_cost_is_private_and_customer_charge_is_in_invoice(client, job_card, customer):
    client.force_login(job_card.mechanic)
    response = client.post(
        reverse("jobcard_part_add", kwargs={"pk": job_card.pk}),
        {
            "part": "",
            "source": "MANUAL",
            "name": "Special alternator",
            "quantity": "2",
            "unit_cost": "8.00",
            "unit_price": "19.00",
            "freight_charge": "6.50",
        },
    )
    assert response.status_code == 302
    item = JobPart.objects.get(job_card=job_card)
    assert (item.name, item.unit_cost, item.unit_price, item.freight_charge) == (
        "Special alternator", Decimal("8.00"), Decimal("19.00"), Decimal("6.50"),
    )
    assert job_card.invoice_total == Decimal("89.50")

    job_card.booking.status = "COMPLETED"
    job_card.booking.save(update_fields=["status"])
    client.force_login(customer)
    invoice = client.get(reverse("jobcard_invoice", kwargs={"pk": job_card.pk}))
    assert b"Special alternator" in invoice.content
    assert b"38.00" in invoice.content
    assert b"6.50" in invoice.content
    assert b"$8.00" not in invoice.content

    exported = client.get(reverse("jobcard_invoice_export", kwargs={"pk": job_card.pk}))
    assert exported.status_code == 200
    assert b"Special alternator" in exported.content
    assert b"38.00" in exported.content
    assert b",8.00," not in exported.content


def test_catalogue_part_uses_workshop_price_by_default(client, job_card, make_part, make_stock):
    part = make_part(price="12.00")
    make_stock(job_card.booking.workshop, part, unit_price=Decimal("15.50"))
    client.force_login(job_card.mechanic)
    response = client.post(
        reverse("jobcard_part_add", kwargs={"pk": job_card.pk}),
        {
            "part": str(part.pk),
            "source": "WAREHOUSE",
            "name": "",
            "quantity": "2",
            "unit_cost": "",
            "unit_price": "",
        },
    )
    assert response.status_code == 302
    item = JobPart.objects.get(job_card=job_card)
    assert (item.name, item.unit_cost, item.unit_price, item.line_total) == (
        part.name, None, Decimal("15.50"), Decimal("31.00"),
    )
    assert item.source == JobPart.Source.WORKSHOP
    stock = job_card.booking.workshop.stock.get(part=part)
    assert stock.quantity == 3


def test_warehouse_part_defaults_freight_and_includes_it_in_customer_invoice(
    client, job_card, make_part, make_stock, warehouse
):
    part = make_part(price="12.00")
    make_stock(job_card.booking.workshop, part, quantity=1)
    make_stock(warehouse, part, unit_price=Decimal("14.00"))
    client.force_login(job_card.mechanic)
    response = client.post(
        reverse("jobcard_part_add", kwargs={"pk": job_card.pk}),
        {
            "part": str(part.pk),
            "source": "WORKSHOP",
            "quantity": "2",
            "unit_cost": "",
            "unit_price": "",
            "freight_charge": "",
        },
    )
    assert response.status_code == 302
    item = JobPart.objects.get(job_card=job_card)
    assert item.source == JobPart.Source.WAREHOUSE
    assert item.supply_status == JobPart.SupplyStatus.READY
    assert item.unit_price == Decimal("14.00")
    assert item.freight_charge == Decimal("12.99")
    assert warehouse.stock.get(part=part).quantity == 3
    assert job_card.invoice_total == Decimal("85.99")

    job_card.booking.status = "COMPLETED"
    job_card.booking.save(update_fields=["status"])
    client.force_login(job_card.booking.customer)
    invoice = client.get(reverse("jobcard_invoice", kwargs={"pk": job_card.pk}))
    assert b"Order from warehouse freight" in invoice.content
    assert b"12.99" in invoice.content
    assert b"85.99" in invoice.content

    exported = client.get(reverse("jobcard_invoice_export", kwargs={"pk": job_card.pk}))
    assert b"Order from warehouse freight" in exported.content
    assert b"12.99" in exported.content


def test_warehouse_part_without_stock_becomes_backorder_and_is_supplier_ordered(
    client, job_card, make_part, warehouse, warehouse_staff
):
    part = make_part(part_number="BACK-1", name="Backordered filter")
    client.force_login(job_card.mechanic)
    add_url = reverse("jobcard_part_add", kwargs={"pk": job_card.pk})
    response = client.post(add_url, {
        "part": str(part.pk),
        "source": "WORKSHOP",
        "quantity": "2",
        "unit_cost": "",
        "unit_price": "18.00",
        "freight_charge": "12.99",
    })
    assert response.status_code == 302
    job_part = JobPart.objects.get(job_card=job_card)
    assert job_part.supply_status == JobPart.SupplyStatus.BACKORDERED
    assert job_part.source == JobPart.Source.WAREHOUSE
    assert job_part.stock_item is None
    assert not warehouse.stock.filter(part=part).exists()

    orders_url = reverse("supplier_order_list")
    assert client.get(orders_url).status_code == 403
    client.force_login(warehouse_staff)
    response = client.get(orders_url)
    assert response.status_code == 200
    assert b"Backordered filter" in response.content

    order_url = reverse("supplier_order_create", kwargs={"part_id": job_part.pk})
    response = client.post(order_url, {
        "supplier": "Parts Supplier",
        "supplier_reference": "PO-123",
        "unit_cost": "7.25",
    })
    assert response.status_code == 302
    job_part.refresh_from_db()
    order = SupplierOrder.objects.get(job_part=job_part)
    assert job_part.supply_status == JobPart.SupplyStatus.ON_ORDER
    assert order.ordered_by == warehouse_staff

    response = client.post(reverse("supplier_order_receive", kwargs={"pk": order.pk}))
    assert response.status_code == 302
    order.refresh_from_db()
    job_part.refresh_from_db()
    warehouse_item = warehouse.stock.get(part=part)
    assert order.received_by == warehouse_staff
    assert order.received_at is not None
    assert job_part.supply_status == JobPart.SupplyStatus.READY
    assert job_part.unit_cost == Decimal("7.25")
    assert job_part.stock_item == warehouse_item
    assert warehouse_item.quantity == 0

    response = client.post(reverse("supplier_order_receive", kwargs={"pk": order.pk}))
    assert response.status_code == 302
    warehouse_item.refresh_from_db()
    assert warehouse_item.quantity == 0


def test_only_warehouse_staff_and_admin_can_manage_supplier_orders(
    client, job_card, make_part, warehouse_staff, admin_user
):
    part = make_part()
    client.force_login(job_card.mechanic)
    client.post(reverse("jobcard_part_add", kwargs={"pk": job_card.pk}), {
        "part": str(part.pk),
        "source": "WAREHOUSE",
        "quantity": "1",
        "unit_cost": "",
        "unit_price": "",
        "freight_charge": "12.99",
    })
    job_part = JobPart.objects.get(job_card=job_card)
    order_url = reverse("supplier_order_create", kwargs={"part_id": job_part.pk})

    client.force_login(job_card.mechanic)
    assert client.get(reverse("supplier_order_list")).status_code == 403
    assert client.get(order_url).status_code == 403

    client.force_login(admin_user)
    assert client.get(reverse("supplier_order_list")).status_code == 200
    assert client.get(reverse("supplier_stock_order_create")).status_code == 200


def test_warehouse_staff_can_order_catalogue_stock_and_receive_it(
    client, warehouse_staff, warehouse, make_part
):
    part = make_part(part_number="STOCK-ORDER", name="Warehouse stock filter")
    client.force_login(warehouse_staff)
    list_url = reverse("supplier_order_list")

    order_page = client.get(list_url)
    assert order_page.status_code == 200
    assert b"Order stock from supplier" in order_page.content
    assert client.get(reverse("supplier_stock_order_create")).status_code == 200

    order_url = reverse("supplier_stock_order_create")
    form_page = client.get(order_url, {"part": part.pk, "quantity": 4})
    form = form_page.context["form"]
    assert form["part"].value() == part.pk
    assert form["quantity"].value() == "4"
    assert form["unit_cost"].value() == part.default_price
    assert b"Search catalogue parts" in form_page.content
    assert b"STOCK-ORDER - Warehouse stock filter" in form_page.content
    assert b'list="part-options"' in form_page.content
    assert f'data-part-id="{part.pk}"'.encode() in form_page.content
    assert b'type="hidden" name="part"' in form_page.content

    response = client.post(reverse("supplier_stock_order_create"), {
        "part": str(part.pk),
        "quantity": "4",
        "supplier": "Warehouse Supplier",
        "supplier_reference": "STOCK-PO-4",
        "unit_cost": "8.50",
    })
    assert response.status_code == 302
    order = SupplierOrder.objects.get(part=part)
    assert order.job_part is None
    assert order.quantity == 4
    assert order.ordered_by == warehouse_staff
    assert not warehouse.stock.filter(part=part).exists()

    response = client.post(reverse("supplier_order_receive", kwargs={"pk": order.pk}))
    assert response.status_code == 302
    order.refresh_from_db()
    stock = warehouse.stock.get(part=part)
    assert order.received_by == warehouse_staff
    assert order.received_at is not None
    assert stock.quantity == 4
    assert stock.unit_cost == Decimal("8.50")

    followup_form = client.get(order_url, {"part": part.pk}).context["form"]
    assert followup_form["unit_cost"].value() == Decimal("8.50")
    client.post(reverse("supplier_order_receive", kwargs={"pk": order.pk}))
    stock.refresh_from_db()
    assert stock.quantity == 4


def test_catalogue_parts_without_stock_are_automatically_backordered(
    client, job_card, make_part
):
    part = make_part()
    client.force_login(job_card.mechanic)
    url = reverse("jobcard_part_add", kwargs={"pk": job_card.pk})
    data = {
        "part": str(part.pk),
        "source": "CATALOGUE",
        "quantity": "1",
        "unit_cost": "",
        "unit_price": "",
        "freight_charge": "",
    }
    response = client.post(url, data)
    assert response.status_code == 302
    item = JobPart.objects.get(job_card=job_card)
    assert item.source == JobPart.Source.WAREHOUSE
    assert item.supply_status == JobPart.SupplyStatus.BACKORDERED
    assert item.freight_charge == Decimal("12.99")


def test_mechanic_can_search_parts_and_sees_workshop_and_warehouse_stock(
    client, job_card, customer, make_part, make_stock, warehouse
):
    part = make_part(part_number="ABC-123", name="Oil filter", universal=True)
    make_stock(job_card.booking.workshop, part, quantity=4)
    make_stock(warehouse, part, quantity=9)
    search_url = reverse("jobcard_part_search", kwargs={"pk": job_card.pk})
    client.force_login(job_card.mechanic)
    response = client.get(search_url, {"q": "ABC"})
    assert response.status_code == 200
    assert response.json()["results"] == [{
        "id": part.pk,
        "label": "ABC-123 — Oil filter",
        "universal": True,
        "workshop_stock": 4,
        "warehouse_stock": 9,
        "workshop_name": job_card.booking.workshop.name,
        "warehouse_name": warehouse.name,
    }]

    client.force_login(customer)
    assert client.get(search_url, {"q": "ABC"}).status_code == 403


def test_part_search_filters_by_vehicle_fitment_including_universal_and_can_show_all(
    client, job_card, customer, make_vehicle, make_part
):
    vehicle = make_vehicle(customer, make="Toyota", model="Corolla", year=2015)
    job_card.booking.vehicle = vehicle
    job_card.booking.save(update_fields=["vehicle"])

    matching = make_part(
        part_number="FIT-2015",
        name="Fitted part",
        fits=(("Toyota", "Corolla", 2010, 2020),),
    )
    make_part(
        part_number="FIT-OLD",
        name="Old fitment",
        fits=(("Toyota", "Corolla", 2000, 2010),),
    )
    universal = make_part(part_number="UNIV-1", name="Universal part", universal=True)
    unrelated = make_part(
        part_number="OTHER-1",
        name="Unrelated fitment",
        fits=(("Honda", "Civic", 2012, 2018),),
    )

    client.force_login(job_card.mechanic)
    url = reverse("jobcard_part_search", kwargs={"pk": job_card.pk})
    response = client.get(url)
    assert response.status_code == 200
    data = response.json()
    result_ids = {result["id"] for result in data["results"]}
    assert result_ids == {matching.pk, universal.pk}
    assert data["filtered_by_vehicle"] is True
    assert data["vehicle"] == str(vehicle)

    entire_catalogue = client.get(url, {"all": "1"}).json()
    all_ids = {result["id"] for result in entire_catalogue["results"]}
    assert {matching.pk, universal.pk, unrelated.pk}.issubset(all_ids)
    assert entire_catalogue["filtered_by_vehicle"] is False


def test_stock_assignment_cannot_go_negative_and_removing_job_part_restores_it(
    client, job_card, make_part, make_stock
):
    part = make_part()
    stock = make_stock(job_card.booking.workshop, part, quantity=1)
    client.force_login(job_card.mechanic)
    url = reverse("jobcard_part_add", kwargs={"pk": job_card.pk})
    data = {
        "part": str(part.pk),
        "source": "WORKSHOP",
        "quantity": "2",
        "unit_cost": "",
        "unit_price": "",
    }

    response = client.post(url, data)
    assert response.status_code == 302
    stock.refresh_from_db()
    assert stock.quantity == 1
    backorder = JobPart.objects.get(job_card=job_card)
    assert backorder.source == JobPart.Source.WAREHOUSE
    assert backorder.supply_status == JobPart.SupplyStatus.BACKORDERED

    data["quantity"] = "1"
    client.post(url, data)
    job_part = JobPart.objects.get(job_card=job_card, supply_status=JobPart.SupplyStatus.READY)
    stock.refresh_from_db()
    assert stock.quantity == 0

    stock.refresh_from_db()
    assert stock.quantity == 0
    assert JobPart.objects.filter(job_card=job_card).count() == 2

    client.post(reverse("jobcard_part_remove", kwargs={"pk": job_card.pk, "part_id": job_part.pk}))
    stock.refresh_from_db()
    assert stock.quantity == 1
    assert not JobPart.objects.filter(pk=job_part.pk).exists()
    assert JobPart.objects.filter(job_card=job_card).count() == 1


def test_mechanic_cannot_assign_parts_to_another_mechanics_job(client, job_card, make_user):
    other = make_user("other-mechanic", role="MECHANIC", workshop=job_card.booking.workshop)
    client.force_login(other)
    response = client.post(
        reverse("jobcard_part_add", kwargs={"pk": job_card.pk}),
        {"part": "", "name": "Part", "quantity": "1", "unit_cost": "1", "unit_price": "2"},
    )
    assert response.status_code == 404
    assert not JobPart.objects.exists()


def test_manual_part_requires_both_internal_cost_and_customer_price(client, job_card):
    client.force_login(job_card.mechanic)
    response = client.post(
        reverse("jobcard_part_add", kwargs={"pk": job_card.pk}),
        {"part": "", "source": "MANUAL", "name": "Special part", "quantity": "1", "unit_cost": "", "unit_price": ""},
    )
    assert response.status_code == 302
    assert not JobPart.objects.exists()
