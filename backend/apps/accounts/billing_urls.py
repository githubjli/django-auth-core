from django.urls import path

from apps.accounts.views import (
    BillingMySubscriptionAPIView,
    BillingPlanListAPIView,
    BillingSubscriptionCancelAPIView,
    BillingSubscriptionCreateAPIView,
)

urlpatterns = [
    path('plans/', BillingPlanListAPIView.as_view(), name='billing-plan-list'),
    path('subscriptions/', BillingSubscriptionCreateAPIView.as_view(), name='billing-subscription-create'),
    path('subscriptions/me/', BillingMySubscriptionAPIView.as_view(), name='billing-subscription-me'),
    path('subscriptions/<int:pk>/cancel/', BillingSubscriptionCancelAPIView.as_view(), name='billing-subscription-cancel'),
]
