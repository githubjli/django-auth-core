from django.urls import path

from apps.accounts.views import (
    PublicUserDetailAPIView,
    PublicUserFollowersListAPIView,
    PublicUserFollowingListAPIView,
)

urlpatterns = [
    path('<int:user_id>/followers/', PublicUserFollowersListAPIView.as_view(), name='public-user-followers'),
    path('<int:user_id>/following/', PublicUserFollowingListAPIView.as_view(), name='public-user-following'),
    path('<int:user_id>/', PublicUserDetailAPIView.as_view(), name='public-user-detail'),
]
