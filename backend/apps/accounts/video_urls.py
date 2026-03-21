from django.urls import path

from apps.accounts.views import VideoDetailAPIView, VideoListCreateAPIView

urlpatterns = [
    path('', VideoListCreateAPIView.as_view(), name='video-list-create'),
    path('<int:pk>/', VideoDetailAPIView.as_view(), name='video-detail'),
]
