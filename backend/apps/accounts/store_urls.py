from django.urls import path

from apps.accounts.views import (
    SellerStoreMeAPIView,
    SellerStoreMeProductDetailAPIView,
    SellerStoreMeProductListCreateAPIView,
)

urlpatterns = [
    path('me/', SellerStoreMeAPIView.as_view(), name='store-me'),
    path('me/products/', SellerStoreMeProductListCreateAPIView.as_view(), name='store-me-products'),
    path('me/products/<int:pk>/', SellerStoreMeProductDetailAPIView.as_view(), name='store-me-product-detail'),
]
