from django.urls import path

from apps.accounts.views import (
    AdminProductOrderMarkSettledAPIView,
    ProductOrderConfirmReceivedAPIView,
    ProductOrderDetailAPIView,
    ProductOrderListCreateAPIView,
    ProductOrderMarkPaidAPIView,
    ProductOrderTxHintAPIView,
    SellerProductOrderDetailAPIView,
    SellerProductOrderListAPIView,
    SellerProductOrderShipAPIView,
)

urlpatterns = [
    path('product-orders/', ProductOrderListCreateAPIView.as_view(), name='product-order-list-create'),
    path('product-orders/<str:order_no>/', ProductOrderDetailAPIView.as_view(), name='product-order-detail'),
    path('product-orders/<str:order_no>/tx-hint/', ProductOrderTxHintAPIView.as_view(), name='product-order-tx-hint'),
    path('product-orders/<str:order_no>/mark-paid/', ProductOrderMarkPaidAPIView.as_view(), name='product-order-mark-paid'),
    path('product-orders/<str:order_no>/confirm-received/', ProductOrderConfirmReceivedAPIView.as_view(), name='product-order-confirm-received'),
    path('seller/product-orders/', SellerProductOrderListAPIView.as_view(), name='seller-product-order-list'),
    path('seller/product-orders/<str:order_no>/', SellerProductOrderDetailAPIView.as_view(), name='seller-product-order-detail'),
    path('seller/product-orders/<str:order_no>/ship/', SellerProductOrderShipAPIView.as_view(), name='seller-product-order-ship'),
    path('admin/product-orders/<str:order_no>/mark-settled/', AdminProductOrderMarkSettledAPIView.as_view(), name='admin-product-order-mark-settled'),
]
