from django.urls import path

from apps.accounts.views import WalletPrototypePayOrderAPIView

urlpatterns = [
    path('pay-order/', WalletPrototypePayOrderAPIView.as_view(), name='wallet-prototype-pay-order'),
]
