from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.PartSearchView.as_view(), name='search'),
    path('<int:pk>/', views.PartDetailView.as_view(), name='detail'),
    path('stock/', views.StockListView.as_view(), name='stock'),
    path('stock/add/', views.StockCreateView.as_view(), name='stock_add'),
    path('stock/transfer/', views.WarehouseStockTransferView.as_view(), name='stock_transfer'),
    path('stock/transfers/<int:pk>/approve/', views.StockTransferRequestDecisionView.as_view(), name='stock_transfer_approve'),
    path('stock/transfers/<int:pk>/reject/', views.StockTransferRequestRejectView.as_view(), name='stock_transfer_reject'),
    path('stock/<int:pk>/edit/', views.StockUpdateView.as_view(), name='stock_edit'),
    path('stock/<int:pk>/delete/', views.StockDeleteView.as_view(), name='stock_delete'),
]
