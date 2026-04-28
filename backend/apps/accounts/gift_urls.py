from django.urls import path

from apps.accounts.gift_views import GiftListAPIView

urlpatterns = [
    path('', GiftListAPIView.as_view(), name='gift-list'),
]
