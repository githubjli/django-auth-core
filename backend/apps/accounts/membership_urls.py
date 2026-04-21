from django.urls import path

from apps.accounts.views import (
    MembershipMeAPIView,
    MembershipOrderCreateAPIView,
    MembershipOrderDetailAPIView,
    MembershipOrderVerifyNowAPIView,
    MembershipOrderTxHintAPIView,
    MembershipPlanListAPIView,
)

urlpatterns = [
    path('plans/', MembershipPlanListAPIView.as_view(), name='membership-plan-list'),
    path('orders/', MembershipOrderCreateAPIView.as_view(), name='membership-order-create'),
    path('orders/<str:order_no>/', MembershipOrderDetailAPIView.as_view(), name='membership-order-detail'),
    path('orders/<str:order_no>/tx-hint/', MembershipOrderTxHintAPIView.as_view(), name='membership-order-tx-hint'),
    path('orders/<str:order_no>/verify-now/', MembershipOrderVerifyNowAPIView.as_view(), name='membership-order-verify-now'),
    path('me/', MembershipMeAPIView.as_view(), name='membership-me'),
]
