from django.urls import path

from apps.accounts.views import CreatorFollowAPIView

urlpatterns = [
    path('<int:pk>/follow/', CreatorFollowAPIView.as_view(), name='creator-follow'),
]
