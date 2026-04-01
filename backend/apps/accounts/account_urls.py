from django.urls import path

from apps.accounts.views import (
    AccountPaymentOrderListAPIView,
    AccountPreferencesAPIView,
    AccountProfileAPIView,
)

urlpatterns = [
    path('profile', AccountProfileAPIView.as_view(), name='account-profile'),
    path('preferences', AccountPreferencesAPIView.as_view(), name='account-preferences'),
    path('payment-orders/', AccountPaymentOrderListAPIView.as_view(), name='account-payment-orders'),
]
