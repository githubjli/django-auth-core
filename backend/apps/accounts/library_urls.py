from django.urls import path

from apps.accounts.library_views import (
    AccountLibraryGiftsReceivedAPIView,
    AccountLibraryGiftsSentAPIView,
    AccountLibraryHistoryAPIView,
    AccountLibraryLikedAPIView,
    AccountLibraryPurchasedAPIView,
)

urlpatterns = [
    path('history/', AccountLibraryHistoryAPIView.as_view(), name='account-library-history'),
    path('liked/', AccountLibraryLikedAPIView.as_view(), name='account-library-liked'),
    path('purchased/', AccountLibraryPurchasedAPIView.as_view(), name='account-library-purchased'),
    path('gifts/sent/', AccountLibraryGiftsSentAPIView.as_view(), name='account-library-gifts-sent'),
    path('gifts/received/', AccountLibraryGiftsReceivedAPIView.as_view(), name='account-library-gifts-received'),
]
