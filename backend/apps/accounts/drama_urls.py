from django.urls import path

from apps.accounts.drama_views import (
    DramaFavoriteAPIView,
    DramaEpisodeDetailAPIView,
    DramaEpisodeListAPIView,
    DramaProgressUpsertAPIView,
    DramaSeriesDetailAPIView,
    DramaSeriesListAPIView,
)

urlpatterns = [
    path('', DramaSeriesListAPIView.as_view(), name='drama-series-list'),
    path('<int:pk>/', DramaSeriesDetailAPIView.as_view(), name='drama-series-detail'),
    path('<int:pk>/episodes/', DramaEpisodeListAPIView.as_view(), name='drama-episode-list'),
    path('<int:pk>/episodes/<int:episode_no>/', DramaEpisodeDetailAPIView.as_view(), name='drama-episode-detail'),
    path('<int:pk>/progress/', DramaProgressUpsertAPIView.as_view(), name='drama-progress-upsert'),
    path('<int:pk>/favorite/', DramaFavoriteAPIView.as_view(), name='drama-favorite'),
]
