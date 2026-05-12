from django.urls import path

from apps.accounts.meow_credit_views import (
    MeowCreditLedgerListAPIView,
    MeowCreditPackageListAPIView,
    MeowCreditRechargeDetailAPIView,
    MeowCreditRechargeListCreateAPIView,
    MeowCreditRechargeTxHintAPIView,
    MeowCreditRedeemListCreateAPIView,
    MeowCreditWalletAPIView,
)

urlpatterns = [
    path('wallet/', MeowCreditWalletAPIView.as_view(), name='meow-credit-wallet'),
    path('packages/', MeowCreditPackageListAPIView.as_view(), name='meow-credit-packages'),
    path('ledger/', MeowCreditLedgerListAPIView.as_view(), name='meow-credit-ledger'),
    path('recharges/', MeowCreditRechargeListCreateAPIView.as_view(), name='meow-credit-recharge-list-create'),
    path('recharges/<str:order_no>/', MeowCreditRechargeDetailAPIView.as_view(), name='meow-credit-recharge-detail'),
    path('recharges/<str:order_no>/tx-hint/', MeowCreditRechargeTxHintAPIView.as_view(), name='meow-credit-recharge-tx-hint'),
    path('redeems/', MeowCreditRedeemListCreateAPIView.as_view(), name='meow-credit-redeem-list-create'),
]
