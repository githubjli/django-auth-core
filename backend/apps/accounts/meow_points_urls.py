from django.urls import path

from apps.accounts.meow_points_views import (
    MeowPointLedgerListAPIView,
    MeowPointOrderDetailAPIView,
    MeowPointOrderListCreateAPIView,
    MeowPointOrderTxHintAPIView,
    MeowPointPackageListAPIView,
    MeowPointWalletAPIView,
)

urlpatterns = [
    path('wallet/', MeowPointWalletAPIView.as_view(), name='meow-point-wallet'),
    path('packages/', MeowPointPackageListAPIView.as_view(), name='meow-point-packages'),
    path('ledger/', MeowPointLedgerListAPIView.as_view(), name='meow-point-ledger'),
    path('orders/', MeowPointOrderListCreateAPIView.as_view(), name='meow-point-order-list-create'),
    path('orders/<str:order_no>/', MeowPointOrderDetailAPIView.as_view(), name='meow-point-order-detail'),
    path('orders/<str:order_no>/tx-hint/', MeowPointOrderTxHintAPIView.as_view(), name='meow-point-order-tx-hint'),
]
