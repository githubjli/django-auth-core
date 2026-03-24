from django.urls import path

from apps.accounts.views import (
    AccountPreferencesAPIView,
    AccountProfileAPIView,
)

urlpatterns = [
    path('profile', AccountProfileAPIView.as_view(), name='account-profile'),
    path('preferences', AccountPreferencesAPIView.as_view(), name='account-preferences'),
]
