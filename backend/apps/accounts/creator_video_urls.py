from django.urls import path

from apps.accounts.views import CreatorVideoListCreateAPIView

urlpatterns = [
    path('', CreatorVideoListCreateAPIView.as_view(), name='creator-video-list-create'),
]
