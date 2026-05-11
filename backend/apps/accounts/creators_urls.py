from django.urls import path

from apps.accounts.views import CreatorFollowAPIView

urlpatterns = [
    path('<int:creator_id>/follow/', CreatorFollowAPIView.as_view(), name='creator-follow'),
]
