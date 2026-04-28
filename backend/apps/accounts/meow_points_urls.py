from django.urls import path

from apps.accounts.meow_points_views import (
    MeowPointLedgerListAPIView,
    MeowPointPackageListAPIView,
    MeowPointWalletAPIView,
)

urlpatterns = [
    path('wallet/', MeowPointWalletAPIView.as_view(), name='meow-point-wallet'),
    path('packages/', MeowPointPackageListAPIView.as_view(), name='meow-point-packages'),
    path('ledger/', MeowPointLedgerListAPIView.as_view(), name='meow-point-ledger'),
]
