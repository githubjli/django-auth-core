from django.urls import path

from apps.accounts.drama_views import (
    DramaCommentListCreateAPIView,
    DramaFavoriteAPIView,
    DramaGiftSendAPIView,
    DramaEpisodeUnlockAPIView,
    DramaEpisodeDetailAPIView,
    DramaEpisodeListAPIView,
    DramaProgressUpsertAPIView,
    DramaEpisodeProgressUpsertAPIView,
    DramaSeriesViewTrackAPIView,
    DramaSeriesDetailAPIView,
    DramaSeriesListAPIView,
    DramaInteractionSummaryAPIView,
    DramaShareAPIView,
)

urlpatterns = [
    path('', DramaSeriesListAPIView.as_view(), name='drama-series-list'),
    path('<int:pk>/', DramaSeriesDetailAPIView.as_view(), name='drama-series-detail'),
    path('<int:pk>/episodes/', DramaEpisodeListAPIView.as_view(), name='drama-episode-list'),
    path('<int:pk>/episodes/<int:episode_no>/', DramaEpisodeDetailAPIView.as_view(), name='drama-episode-detail'),
    path('episodes/<int:episode_id>/unlock/', DramaEpisodeUnlockAPIView.as_view(), name='drama-episode-unlock'),
    path('<int:pk>/progress/', DramaProgressUpsertAPIView.as_view(), name='drama-progress-upsert'),
    path('episodes/<int:episode_id>/progress/', DramaEpisodeProgressUpsertAPIView.as_view(), name='drama-episode-progress-upsert'),
    path('<int:pk>/favorite/', DramaFavoriteAPIView.as_view(), name='drama-favorite'),
    path('<int:pk>/gifts/send/', DramaGiftSendAPIView.as_view(), name='drama-gift-send'),
    path('<int:pk>/comments/', DramaCommentListCreateAPIView.as_view(), name='drama-comments'),
    path('<int:pk>/share/', DramaShareAPIView.as_view(), name='drama-share'),
    path('<int:pk>/interaction-summary/', DramaInteractionSummaryAPIView.as_view(), name='drama-interaction-summary'),
    path('<int:pk>/view/', DramaSeriesViewTrackAPIView.as_view(), name='drama-series-view-track'),
]
