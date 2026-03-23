from django.urls import path

from apps.accounts.views import (
    PublicRelatedVideoListAPIView,
    PublicVideoDetailAPIView,
    PublicVideoListAPIView,
    PublicVideoViewTrackAPIView,
)

urlpatterns = [
    path('', PublicVideoListAPIView.as_view(), name='public-video-list'),
    path('<int:pk>/', PublicVideoDetailAPIView.as_view(), name='public-video-detail'),
    path('<int:pk>/related/', PublicRelatedVideoListAPIView.as_view(), name='public-video-related'),
    path('<int:pk>/view/', PublicVideoViewTrackAPIView.as_view(), name='public-video-view'),
]
