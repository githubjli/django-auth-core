from django.urls import path

from apps.accounts.views import (
    SellerProductOrderDetailAPIView,
    SellerProductOrderListAPIView,
    SellerProductOrderShipAPIView,
    SellerStoreMeProductDetailAPIView,
    SellerStoreMeProductListCreateAPIView,
)

urlpatterns = [
    path('products/', SellerStoreMeProductListCreateAPIView.as_view(), name='creator-shop-products'),
    path('products/<int:pk>/', SellerStoreMeProductDetailAPIView.as_view(), name='creator-shop-product-detail'),
    path('orders/', SellerProductOrderListAPIView.as_view(), name='creator-shop-orders'),
    path('orders/<str:order_no>/', SellerProductOrderDetailAPIView.as_view(), name='creator-shop-order-detail'),
    path('orders/<str:order_no>/ship/', SellerProductOrderShipAPIView.as_view(), name='creator-shop-order-ship'),
]
