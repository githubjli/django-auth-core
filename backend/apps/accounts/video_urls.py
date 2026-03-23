from django.urls import path

from apps.accounts.views import (
    VideoDetailAPIView,
    VideoLikeAPIView,
    VideoListCreateAPIView,
    VideoRegenerateThumbnailAPIView,
    VideoUnlikeAPIView,
)

urlpatterns = [
    path('', VideoListCreateAPIView.as_view(), name='video-list-create'),
    path('<int:pk>/', VideoDetailAPIView.as_view(), name='video-detail'),
    path(
        '<int:pk>/regenerate-thumbnail/',
        VideoRegenerateThumbnailAPIView.as_view(),
        name='video-regenerate-thumbnail',
    ),
    path('<int:pk>/like/', VideoLikeAPIView.as_view(), name='video-like'),
    path('<int:pk>/unlike/', VideoUnlikeAPIView.as_view(), name='video-unlike'),
]
