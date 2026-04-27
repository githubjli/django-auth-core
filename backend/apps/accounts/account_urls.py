from django.urls import path

from apps.accounts.views import (
    AccountPasswordChangeAPIView,
    AccountPaymentOrderListAPIView,
    AccountPreferencesAPIView,
    AccountProfileAPIView,
    AccountShippingAddressDetailAPIView,
    AccountShippingAddressListCreateAPIView,
)
from apps.accounts.drama_views import AccountDramaFavoritesListAPIView, AccountDramaProgressListAPIView

urlpatterns = [
    path('profile', AccountProfileAPIView.as_view(), name='account-profile'),
    path('preferences', AccountPreferencesAPIView.as_view(), name='account-preferences'),
    path('change-password/', AccountPasswordChangeAPIView.as_view(), name='account-change-password'),
    path('payment-orders/', AccountPaymentOrderListAPIView.as_view(), name='account-payment-orders'),
    path('shipping-addresses/', AccountShippingAddressListCreateAPIView.as_view(), name='account-shipping-address-list-create'),
    path('shipping-addresses/<int:id>/', AccountShippingAddressDetailAPIView.as_view(), name='account-shipping-address-detail'),
    path('drama-progress/', AccountDramaProgressListAPIView.as_view(), name='account-drama-progress'),
    path('drama-favorites/', AccountDramaFavoritesListAPIView.as_view(), name='account-drama-favorites'),
]
