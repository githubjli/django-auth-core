from django.urls import path

from apps.accounts.views import (
    SellerApplicationCreateAPIView,
    SellerApplicationMeAPIView,
)

urlpatterns = [
    path('', SellerApplicationCreateAPIView.as_view(), name='seller-application-create'),
    path('me/', SellerApplicationMeAPIView.as_view(), name='seller-application-me'),
]
