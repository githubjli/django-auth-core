from django.urls import path

from apps.accounts.views import PublicSellerStoreDetailAPIView, PublicSellerStoreProductListAPIView

urlpatterns = [
    path('<slug:slug>/', PublicSellerStoreDetailAPIView.as_view(), name='public-store-detail'),
    path('<slug:slug>/products/', PublicSellerStoreProductListAPIView.as_view(), name='public-store-products'),
]
