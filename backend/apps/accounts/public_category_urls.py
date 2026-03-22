from django.urls import path

from apps.accounts.views import PublicCategoryListAPIView

urlpatterns = [
    path('', PublicCategoryListAPIView.as_view(), name='public-category-list'),
]
