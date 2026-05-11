from django.urls import path

from apps.accounts.views import (
    PublicRelatedVideoListAPIView,
    PublicVideoCommentListAPIView,
    PublicVideoDetailAPIView,
    PublicVideoGiftSendAPIView,
    PublicVideoInteractionSummaryAPIView,
    PublicVideoListAPIView,
    PublicVideoShareTrackAPIView,
    PublicVideoViewTrackAPIView,
)

urlpatterns = [
    path('', PublicVideoListAPIView.as_view(), name='public-video-list'),
    path('<int:pk>/', PublicVideoDetailAPIView.as_view(), name='public-video-detail'),
    path('<int:pk>/related/', PublicRelatedVideoListAPIView.as_view(), name='public-video-related'),
    path('<int:pk>/interaction-summary/', PublicVideoInteractionSummaryAPIView.as_view(), name='public-video-interaction-summary'),
    path('<int:pk>/share/', PublicVideoShareTrackAPIView.as_view(), name='public-video-share'),
    path('<int:pk>/gifts/send/', PublicVideoGiftSendAPIView.as_view(), name='public-video-gift-send'),
    path('<int:pk>/comments/', PublicVideoCommentListAPIView.as_view(), name='public-video-comments'),
    path('<int:pk>/view/', PublicVideoViewTrackAPIView.as_view(), name='public-video-view'),
]
