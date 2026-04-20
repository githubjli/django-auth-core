from django.urls import path

from apps.accounts.views import (
    MembershipMeAPIView,
    MembershipOrderCreateAPIView,
    MembershipOrderDetailAPIView,
    MembershipPlanListAPIView,
)

urlpatterns = [
    path('plans/', MembershipPlanListAPIView.as_view(), name='membership-plan-list'),
    path('orders/', MembershipOrderCreateAPIView.as_view(), name='membership-order-create'),
    path('orders/<str:order_no>/', MembershipOrderDetailAPIView.as_view(), name='membership-order-detail'),
    path('me/', MembershipMeAPIView.as_view(), name='membership-me'),
]
