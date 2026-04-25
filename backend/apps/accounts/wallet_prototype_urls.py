from django.urls import path

from apps.accounts.views import WalletPrototypePayOrderAPIView, WalletPrototypePayProductOrderAPIView

urlpatterns = [
    path('pay-order/', WalletPrototypePayOrderAPIView.as_view(), name='wallet-prototype-pay-order'),
    path('pay-product-order/', WalletPrototypePayProductOrderAPIView.as_view(), name='wallet-prototype-pay-product-order'),
]
