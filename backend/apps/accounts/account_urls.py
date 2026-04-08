from django.urls import path

from apps.accounts.views import (
    AccountPasswordChangeAPIView,
    AccountPaymentOrderListAPIView,
    AccountPreferencesAPIView,
    AccountProfileAPIView,
)

urlpatterns = [
    path('profile', AccountProfileAPIView.as_view(), name='account-profile'),
    path('preferences', AccountPreferencesAPIView.as_view(), name='account-preferences'),
    path('change-password/', AccountPasswordChangeAPIView.as_view(), name='account-change-password'),
    path('payment-orders/', AccountPaymentOrderListAPIView.as_view(), name='account-payment-orders'),
]
