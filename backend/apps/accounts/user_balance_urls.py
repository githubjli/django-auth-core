from django.urls import path

from apps.accounts.gift_views import UserBalanceAPIView

urlpatterns = [
    path('balance/', UserBalanceAPIView.as_view(), name='user-balance'),
]
