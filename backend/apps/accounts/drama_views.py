from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.drama_serializers import DramaEpisodeSerializer, DramaSeriesSerializer
from apps.accounts.models import DramaEpisode, DramaSeries


class DramaSeriesPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class DramaSeriesListAPIView(generics.ListAPIView):
    serializer_class = DramaSeriesSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        queryset = (
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED)
            .annotate(
                free_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=True)),
                locked_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=False)),
            )
            .order_by('-created_at', '-id')
        )

        category = self.request.query_params.get('category')
        if category:
            if category.isdigit():
                queryset = queryset.filter(category_id=int(category))
            else:
                queryset = queryset.filter(category__slug=category)

        return queryset


class DramaSeriesDetailAPIView(generics.RetrieveAPIView):
    serializer_class = DramaSeriesSerializer

    def get_queryset(self):
        return DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED).annotate(
            free_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=True)),
            locked_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=False)),
        )


class DramaEpisodeListAPIView(APIView):
    def get(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        episodes = DramaEpisode.objects.filter(series=series, is_active=True).order_by('sort_order', 'episode_no', 'id')
        serializer = DramaEpisodeSerializer(episodes, many=True, context={'request': request})
        return Response({'series_id': series.id, 'episodes': serializer.data})


class DramaEpisodeDetailAPIView(APIView):
    def get(self, request, pk, episode_no):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        episode = get_object_or_404(
            DramaEpisode.objects.filter(series=series, is_active=True),
            episode_no=episode_no,
        )
        serializer = DramaEpisodeSerializer(episode, context={'request': request})
        return Response(serializer.data)
