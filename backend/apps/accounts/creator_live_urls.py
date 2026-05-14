from django.urls import path

from apps.accounts.views import CreatorLiveStreamListAPIView

urlpatterns = [
    path('', CreatorLiveStreamListAPIView.as_view(), name='creator-live-stream-list'),
]
