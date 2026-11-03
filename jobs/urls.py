from django.urls import path

from . import views

urlpatterns = [
    path("", views.JobCardListView.as_view(), name="jobcard_list"),
    path("supplier-orders/", views.SupplierOrderListView.as_view(), name="supplier_order_list"),
    path(
        "supplier-orders/backorders/<int:part_id>/order/",
        views.SupplierOrderCreateView.as_view(),
        name="supplier_order_create",
    ),
    path(
        "supplier-orders/order/",
        views.SupplierOrderCreateView.as_view(),
        name="supplier_stock_order_create",
    ),
    path(
        "supplier-orders/<int:pk>/receive/",
        views.SupplierOrderReceiveView.as_view(),
        name="supplier_order_receive",
    ),
    path("<int:pk>/parts/search/", views.PartSearchView.as_view(), name="jobcard_part_search"),
    path("create/<int:booking_id>/", views.JobCardCreateView.as_view(), name="jobcard_create"),
    path("<int:pk>/invoice/", views.InvoiceView.as_view(), name="jobcard_invoice"),
    path("<int:pk>/invoice.csv", views.InvoiceExportView.as_view(), name="jobcard_invoice_export"),
    path("<int:pk>/parts/add/", views.JobPartCreateView.as_view(), name="jobcard_part_add"),
    path("<int:pk>/parts/<int:part_id>/remove/", views.JobPartDeleteView.as_view(), name="jobcard_part_remove"),
    path("<int:pk>/", views.JobCardDetailView.as_view(), name="jobcard_detail"),
]