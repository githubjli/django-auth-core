from django.urls import path

from apps.accounts.drama_views import (
    CreatorDramaEpisodeDetailAPIView,
    CreatorDramaEpisodeListCreateAPIView,
    CreatorDramaSeriesDetailAPIView,
    CreatorDramaSeriesListCreateAPIView,
)

urlpatterns = [
    path('', CreatorDramaSeriesListCreateAPIView.as_view(), name='creator-drama-series-list-create'),
    path('<int:pk>/', CreatorDramaSeriesDetailAPIView.as_view(), name='creator-drama-series-detail'),
    path('<int:pk>/episodes/', CreatorDramaEpisodeListCreateAPIView.as_view(), name='creator-drama-episode-list-create'),
    path('<int:pk>/episodes/<int:episode_id>/', CreatorDramaEpisodeDetailAPIView.as_view(), name='creator-drama-episode-detail'),
]
