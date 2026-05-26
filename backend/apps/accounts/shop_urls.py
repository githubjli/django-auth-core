from django.urls import path

from apps.accounts.views import (
    ShopBannerListAPIView,
    ShopCategoryListAPIView,
    ShopProductDetailAPIView,
    ShopProductListAPIView,
)

urlpatterns = [
    path('banners/', ShopBannerListAPIView.as_view(), name='shop-banner-list'),
    path('categories/', ShopCategoryListAPIView.as_view(), name='shop-category-list'),
    path('products/', ShopProductListAPIView.as_view(), name='shop-product-list'),
    path('products/<int:id>/', ShopProductDetailAPIView.as_view(), name='shop-product-detail'),
]
